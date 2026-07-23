#!/usr/bin/env python3

# Copyright (c) 2019 Computer Vision Center (CVC) at the Universitat Autonoma de
# Barcelona (UAB).
#
# This work is licensed under the terms of the MIT license.
# For a copy, see <https://opensource.org/licenses/MIT>.

# Allows controlling a vehicle with a keyboard. For a simpler and more
# documented example, please take a look at tutorial.py.


"""
CARLA 0.10 manual keyboard control for Python 3.10 and pygame-ce.

Controls
--------
W / Up Arrow       Throttle with speed limiter
S / Down Arrow     Brake
A/D or Left/Right  Steering
Q                  Toggle reverse
Space              Hand brake
P                  Toggle autopilot
M                  Toggle manual transmission
, / .              Gear down/up

Ctrl+W             Toggle constant velocity at 60 km/h
L                  Cycle vehicle lights
Shift+L            Toggle high beam
Ctrl+L             Toggle special light
Z/X                Toggle left/right blinker
I                  Toggle interior light

Tab                Change camera position
` or N             Next sensor
1-9                Select sensor
G                  Toggle radar
C / Shift+C        Next/previous weather
Backspace          Respawn vehicle

R                  Toggle image recording
Ctrl+R             Toggle CARLA simulation recording
Ctrl+P             Replay last CARLA recording
Ctrl+- / Ctrl+=    Adjust replay start time
Shift adds 10 seconds instead of 1

F1                 Toggle HUD
H or ?             Toggle help
Esc or Ctrl+Q      Quit
"""

from __future__ import annotations

import argparse
import collections
import datetime
import faulthandler
import logging
import math
import os
import random
import re
import weakref
from pathlib import Path

import numpy as np
import carla
from carla import ColorConverter as cc
import pygame
from pygame.locals import (
    K_0,
    K_9,
    K_BACKQUOTE,
    K_BACKSPACE,
    K_COMMA,
    K_DOWN,
    K_EQUALS,
    K_ESCAPE,
    K_F1,
    K_LEFT,
    K_MINUS,
    K_PERIOD,
    K_RIGHT,
    K_SLASH,
    K_SPACE,
    K_TAB,
    K_UP,
    KMOD_CTRL,
    KMOD_SHIFT,
    K_a,
    K_c,
    K_d,
    K_g,
    K_h,
    K_i,
    K_l,
    K_m,
    K_n,
    K_p,
    K_q,
    K_r,
    K_s,
    K_w,
    K_x,
    K_z,
)

faulthandler.enable()

RECORDING_FILE = "manual_recording.rec"
IMAGE_OUTPUT_DIRECTORY = Path("_out")


def clamp(value, minimum, maximum):
    return max(minimum, min(value, maximum))


def safe_stop_and_destroy(actor):
    if actor is None:
        return

    try:
        if getattr(actor, "is_listening", False):
            actor.stop()
    except (AttributeError, RuntimeError):
        pass

    try:
        if getattr(actor, "is_alive", True):
            actor.destroy()
    except RuntimeError:
        pass


def spring_arm_attachment():
    attachment = carla.AttachmentType

    if hasattr(attachment, "SpringArmGhost"):
        return attachment.SpringArmGhost

    if hasattr(attachment, "SpringArm"):
        return attachment.SpringArm

    return attachment.Rigid


def find_weather_presets():
    pattern = re.compile(
        r".+?(?:(?<=[a-z])(?=[A-Z])|"
        r"(?<=[A-Z])(?=[A-Z][a-z])|$)"
    )

    def pretty_name(value):
        return " ".join(match.group(0) for match in pattern.finditer(value))

    presets = []
    for name in dir(carla.WeatherParameters):
        if not re.match(r"[A-Z].+", name):
            continue

        value = getattr(carla.WeatherParameters, name)
        presets.append((value, pretty_name(name)))

    return presets


def get_actor_display_name(actor, truncate=250):
    name = " ".join(actor.type_id.replace("_", ".").title().split(".")[1:])

    if len(name) > truncate:
        return name[: truncate - 1] + "\N{HORIZONTAL ELLIPSIS}"

    return name


class World:
    def __init__(self, carla_world, hud, args):
        self.world = carla_world
        self.hud = hud
        self.args = args
        self.actor_role_name = args.rolename

        try:
            self.map = self.world.get_map()
        except RuntimeError as error:
            raise RuntimeError(
                "The server could not provide the map OpenDRIVE file. "
                "Verify that the map and its .xodr data are installed."
            ) from error

        self.player = None
        self.collision_sensor = None
        self.lane_invasion_sensor = None
        self.gnss_sensor = None
        self.imu_sensor = None
        self.radar_sensor = None
        self.camera_manager = None

        self.player_max_speed = 1.589
        self.player_max_speed_fast = 3.713

        self._weather_presets = find_weather_presets()
        self._weather_index = 0
        self._actor_filter = args.filter
        self._generation = args.generation
        self._gamma = args.gamma

        self.recording_enabled = False
        self.recording_start = 0
        self.constant_velocity_enabled = False

        self.restart()
        self.world.on_tick(self.hud.on_world_tick)

    def _get_actor_blueprints(self):
        blueprints = list(self.world.get_blueprint_library().filter(self._actor_filter))

        if not blueprints:
            raise RuntimeError(f"No actor blueprints matched {self._actor_filter!r}.")

        if self._generation.lower() == "all":
            return blueprints

        try:
            generation = int(self._generation)
        except ValueError as error:
            raise RuntimeError(
                f"Invalid actor generation: {self._generation!r}"
            ) from error

        filtered = []
        for blueprint in blueprints:
            if not blueprint.has_attribute("generation"):
                continue

            try:
                if int(blueprint.get_attribute("generation")) == generation:
                    filtered.append(blueprint)
            except (TypeError, ValueError):
                continue

        if not filtered:
            logging.warning(
                "No blueprints matched generation %s; using all generations.",
                generation,
            )
            return blueprints

        return filtered

    def _prepare_blueprint(self):
        blueprint = random.choice(self._get_actor_blueprints())
        blueprint.set_attribute("role_name", self.actor_role_name)

        for attribute_name in ("color", "driver_id"):
            if not blueprint.has_attribute(attribute_name):
                continue

            values = blueprint.get_attribute(attribute_name).recommended_values
            if values:
                blueprint.set_attribute(
                    attribute_name,
                    random.choice(values),
                )

        if blueprint.has_attribute("is_invincible"):
            blueprint.set_attribute("is_invincible", "true")

        if blueprint.has_attribute("speed"):
            values = blueprint.get_attribute("speed").recommended_values
            try:
                if len(values) > 1:
                    self.player_max_speed = float(values[1])
                if len(values) > 2:
                    self.player_max_speed_fast = float(values[2])
            except (TypeError, ValueError):
                logging.warning(
                    "Blueprint %s has invalid speed recommendations.",
                    blueprint.id,
                )

        return blueprint

    def _get_spawn_points(self, previous_transform):
        custom_spawn = all(
            value is not None
            for value in (
                self.args.x,
                self.args.y,
                self.args.z,
            )
        )

        if custom_spawn:
            return [
                carla.Transform(
                    carla.Location(
                        x=self.args.x,
                        y=self.args.y,
                        z=self.args.z,
                    ),
                    carla.Rotation(
                        roll=self.args.roll,
                        pitch=self.args.pitch,
                        yaw=self.args.yaw,
                    ),
                )
            ]

        spawn_points = list(self.map.get_spawn_points())
        random.shuffle(spawn_points)

        if previous_transform is not None:
            spawn_points.insert(0, previous_transform)

        return spawn_points

    def restart(self):
        camera_index = 0
        camera_position = 0
        previous_transform = None

        if self.camera_manager is not None:
            if self.camera_manager.index is not None:
                camera_index = self.camera_manager.index
            camera_position = self.camera_manager.transform_index

        if self.player is not None:
            previous_transform = self.player.get_transform()
            previous_transform.location.z += 2.0
            previous_transform.rotation.roll = 0.0
            previous_transform.rotation.pitch = 0.0

        if self.constant_velocity_enabled and self.player is not None:
            try:
                self.player.disable_constant_velocity()
            except RuntimeError:
                pass

        self.constant_velocity_enabled = False
        self.destroy()

        blueprint = self._prepare_blueprint()
        spawn_points = self._get_spawn_points(previous_transform)

        if not spawn_points:
            raise RuntimeError("The map contains no vehicle spawn points.")

        for spawn_point in spawn_points:
            self.player = self.world.try_spawn_actor(
                blueprint,
                spawn_point,
            )
            if self.player is not None:
                break

        if self.player is None:
            raise RuntimeError(
                "Unable to spawn the player actor. The requested spawn "
                "point or all map spawn points may be occupied."
            )

        self.collision_sensor = CollisionSensor(
            self.player,
            self.hud,
        )
        self.lane_invasion_sensor = LaneInvasionSensor(
            self.player,
            self.hud,
        )
        self.gnss_sensor = GnssSensor(self.player)
        self.imu_sensor = IMUSensor(self.player)
        self.camera_manager = CameraManager(
            self.player,
            self.hud,
            self._gamma,
        )

        self.camera_manager.transform_index = camera_position % len(
            self.camera_manager.camera_transforms
        )
        self.camera_manager.set_sensor(camera_index, notify=False)

        self.hud.notification(get_actor_display_name(self.player))

    def next_weather(self, reverse=False):
        if not self._weather_presets:
            self.hud.notification("No weather presets available")
            return

        self._weather_index += -1 if reverse else 1
        self._weather_index %= len(self._weather_presets)

        weather, name = self._weather_presets[self._weather_index]
        self.world.set_weather(weather)
        self.hud.notification(f"Weather: {name}")

    def toggle_radar(self):
        if self.radar_sensor is None:
            self.radar_sensor = RadarSensor(self.player)
            self.hud.notification("Radar visualization enabled")
            return

        safe_stop_and_destroy(self.radar_sensor.sensor)
        self.radar_sensor.sensor = None
        self.radar_sensor = None
        self.hud.notification("Radar visualization disabled")

    def tick(self, clock):
        self.hud.tick(self, clock)

    def render(self, display):
        if self.camera_manager is not None:
            self.camera_manager.render(display)
        self.hud.render(display)

    def destroy_sensors(self):
        if self.camera_manager is None:
            return

        safe_stop_and_destroy(self.camera_manager.sensor)
        self.camera_manager.sensor = None
        self.camera_manager.surface = None
        self.camera_manager.index = None

    def destroy(self):
        if self.radar_sensor is not None:
            safe_stop_and_destroy(self.radar_sensor.sensor)
            self.radar_sensor.sensor = None
            self.radar_sensor = None

        wrappers = (
            self.camera_manager,
            self.collision_sensor,
            self.lane_invasion_sensor,
            self.gnss_sensor,
            self.imu_sensor,
        )

        for wrapper in wrappers:
            if wrapper is None:
                continue

            safe_stop_and_destroy(getattr(wrapper, "sensor", None))
            wrapper.sensor = None

        safe_stop_and_destroy(self.player)
        self.player = None

        self.camera_manager = None
        self.collision_sensor = None
        self.lane_invasion_sensor = None
        self.gnss_sensor = None
        self.imu_sensor = None


class KeyboardControl:
    def __init__(self, world, start_in_autopilot):
        self._autopilot_enabled = start_in_autopilot
        self._steer_cache = 0.0
        self._previous_speed_error = 0.0

        if isinstance(world.player, carla.Vehicle):
            self._control = carla.VehicleControl()
            self._lights = carla.VehicleLightState.NONE
            world.player.set_autopilot(self._autopilot_enabled)
            world.player.set_light_state(self._lights)
        elif isinstance(world.player, carla.Walker):
            self._control = carla.WalkerControl()
            self._rotation = world.player.get_transform().rotation
            self._autopilot_enabled = False
        else:
            raise NotImplementedError("Only vehicles and walkers are supported.")

        world.hud.notification(
            "Press H or ? for help.",
            seconds=4.0,
        )

    def _restore_control_after_restart(self, world):
        self._steer_cache = 0.0
        self._previous_speed_error = 0.0

        if isinstance(world.player, carla.Vehicle):
            self._control = carla.VehicleControl()
            world.player.set_autopilot(self._autopilot_enabled)
            world.player.set_light_state(self._lights)
        elif isinstance(world.player, carla.Walker):
            self._control = carla.WalkerControl()
            self._rotation = world.player.get_transform().rotation
            self._autopilot_enabled = False

    def parse_events(self, client, world, clock):
        current_lights = self._lights

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return True

            if event.type != pygame.KEYUP:
                continue

            modifiers = pygame.key.get_mods()

            if self._is_quit_shortcut(event.key):
                return True

            if event.key == K_BACKSPACE:
                was_autopilot = self._autopilot_enabled

                if was_autopilot and isinstance(
                    world.player,
                    carla.Vehicle,
                ):
                    world.player.set_autopilot(False)

                world.restart()
                self._autopilot_enabled = was_autopilot
                self._restore_control_after_restart(world)
                current_lights = self._lights

            elif event.key == K_F1:
                world.hud.toggle_info()

            elif event.key == K_h or (event.key == K_SLASH and modifiers & KMOD_SHIFT):
                world.hud.help.toggle()

            elif event.key == K_TAB:
                world.camera_manager.toggle_camera()

            elif event.key == K_c and modifiers & KMOD_SHIFT:
                world.next_weather(reverse=True)

            elif event.key == K_c:
                world.next_weather()

            elif event.key == K_g:
                world.toggle_radar()

            elif event.key in (K_BACKQUOTE, K_n):
                world.camera_manager.next_sensor()

            elif event.key == K_w and modifiers & KMOD_CTRL:
                if not isinstance(world.player, carla.Vehicle):
                    continue

                if world.constant_velocity_enabled:
                    world.player.disable_constant_velocity()
                    world.constant_velocity_enabled = False
                    world.hud.notification("Constant velocity disabled")
                else:
                    world.player.enable_constant_velocity(carla.Vector3D(x=60.0 / 3.6))
                    world.constant_velocity_enabled = True
                    world.hud.notification("Constant velocity enabled at 60 km/h")

            elif K_0 < event.key <= K_9:
                world.camera_manager.set_sensor(event.key - K_0 - 1)

            elif event.key == K_r and not modifiers & KMOD_CTRL:
                world.camera_manager.toggle_recording()

            elif event.key == K_r and modifiers & KMOD_CTRL:
                if world.recording_enabled:
                    client.stop_recorder()
                    world.recording_enabled = False
                    world.hud.notification("Recorder is OFF")
                else:
                    client.start_recorder(RECORDING_FILE)
                    world.recording_enabled = True
                    world.hud.notification("Recorder is ON")

            elif event.key == K_p and modifiers & KMOD_CTRL:
                client.stop_recorder()
                world.recording_enabled = False

                current_index = world.camera_manager.index
                world.destroy_sensors()

                self._autopilot_enabled = False
                if isinstance(world.player, carla.Vehicle):
                    world.player.set_autopilot(False)

                world.hud.notification(f"Replaying {RECORDING_FILE!r}")
                client.replay_file(
                    RECORDING_FILE,
                    world.recording_start,
                    0,
                    0,
                )
                world.camera_manager.set_sensor(current_index)

            elif event.key == K_MINUS and modifiers & KMOD_CTRL:
                amount = 10 if modifiers & KMOD_SHIFT else 1
                world.recording_start -= amount
                world.hud.notification(
                    f"Recording start time: {world.recording_start} seconds"
                )

            elif event.key == K_EQUALS and modifiers & KMOD_CTRL:
                amount = 10 if modifiers & KMOD_SHIFT else 1
                world.recording_start += amount
                world.hud.notification(
                    f"Recording start time: {world.recording_start} seconds"
                )

            if not isinstance(
                self._control,
                carla.VehicleControl,
            ):
                continue

            if event.key == K_q:
                self._control.gear = 1 if self._control.reverse else -1

            elif event.key == K_m:
                self._control.manual_gear_shift = not self._control.manual_gear_shift
                self._control.gear = world.player.get_control().gear
                mode = "Manual" if self._control.manual_gear_shift else "Automatic"
                world.hud.notification(f"{mode} transmission")

            elif self._control.manual_gear_shift and event.key == K_COMMA:
                self._control.gear = max(
                    -1,
                    self._control.gear - 1,
                )

            elif self._control.manual_gear_shift and event.key == K_PERIOD:
                self._control.gear += 1

            elif event.key == K_p and not modifiers & KMOD_CTRL:
                self._autopilot_enabled = not self._autopilot_enabled
                world.player.set_autopilot(self._autopilot_enabled)
                state = "On" if self._autopilot_enabled else "Off"
                world.hud.notification(f"Autopilot {state}")

            elif event.key == K_l and modifiers & KMOD_CTRL:
                current_lights ^= carla.VehicleLightState.Special1

            elif event.key == K_l and modifiers & KMOD_SHIFT:
                current_lights ^= carla.VehicleLightState.HighBeam

            elif event.key == K_l:
                position = carla.VehicleLightState.Position
                low_beam = carla.VehicleLightState.LowBeam
                fog = carla.VehicleLightState.Fog

                if not self._lights & position:
                    current_lights |= position
                    world.hud.notification("Position lights")
                elif not self._lights & low_beam:
                    current_lights |= low_beam
                    world.hud.notification("Low-beam lights")
                elif not self._lights & fog:
                    current_lights |= fog
                    world.hud.notification("Fog lights")
                else:
                    current_lights &= ~position
                    current_lights &= ~low_beam
                    current_lights &= ~fog
                    world.hud.notification("Lights off")

            elif event.key == K_i:
                current_lights ^= carla.VehicleLightState.Interior

            elif event.key == K_z:
                current_lights ^= carla.VehicleLightState.LeftBlinker

            elif event.key == K_x:
                current_lights ^= carla.VehicleLightState.RightBlinker

        if isinstance(self._control, carla.VehicleControl):
            if current_lights != self._lights:
                self._lights = current_lights
                world.player.set_light_state(carla.VehicleLightState(self._lights))

        if self._autopilot_enabled:
            return False

        keys = pygame.key.get_pressed()

        if isinstance(self._control, carla.VehicleControl):
            self._parse_vehicle_keys(
                keys,
                clock.get_time(),
                world,
            )
            self._control.reverse = self._control.gear < 0

            if self._control.brake:
                current_lights |= carla.VehicleLightState.Brake
            else:
                current_lights &= ~carla.VehicleLightState.Brake

            if self._control.reverse:
                current_lights |= carla.VehicleLightState.Reverse
            else:
                current_lights &= ~carla.VehicleLightState.Reverse

            if current_lights != self._lights:
                self._lights = current_lights
                world.player.set_light_state(carla.VehicleLightState(self._lights))

            world.player.apply_control(self._control)

        elif isinstance(self._control, carla.WalkerControl):
            self._parse_walker_keys(
                keys,
                clock.get_time(),
                world,
            )
            world.player.apply_control(self._control)  # type: ignore

        return False

    def _parse_vehicle_keys(self, keys, milliseconds, world):
        if not isinstance(self._control, carla.VehicleControl):
            return

        velocity = world.player.get_velocity()
        speed_kph = 3.6 * math.sqrt(velocity.x**2 + velocity.y**2 + velocity.z**2)
        dt = clamp(milliseconds / 1000.0, 0.001, 0.1)
        throttle_pressed = bool(keys[K_UP] or keys[K_w])
        brake_pressed = bool(keys[K_DOWN] or keys[K_s])

        if throttle_pressed and not brake_pressed:
            error = world.args.speed_limit - speed_kph
            derivative = (error - self._previous_speed_error) / dt

            kp = 0.08
            kd = 0.002
            target_throttle = clamp(
                kp * error + kd * derivative,
                0.0,
                1.0,
            )

            alpha = clamp(4.0 * dt, 0.0, 1.0)
            self._control.throttle += alpha * (target_throttle - self._control.throttle)
            self._control.throttle = clamp(
                self._control.throttle,
                0.0,
                1.0,
            )

            if error < -1.0:
                self._control.brake = clamp(
                    (-error - 1.0) * 0.025,
                    0.0,
                    0.35,
                )
            else:
                self._control.brake = 0.0

            self._previous_speed_error = error
        else:
            self._control.throttle = max(
                0.0,
                self._control.throttle - 2.0 * dt,
            )
            self._control.brake = 0.0
            self._previous_speed_error = 0.0

        if brake_pressed:
            self._control.throttle = 0.0
            self._control.brake = min(
                1.0,
                self._control.brake + 3.5 * dt,
            )

        steer_increment = 1.5 * dt
        steer_return = 4.0 * dt

        if keys[K_LEFT] or keys[K_a]:
            if self._steer_cache > 0.0:
                self._steer_cache = 0.0
            self._steer_cache -= steer_increment

        elif keys[K_RIGHT] or keys[K_d]:
            if self._steer_cache < 0.0:
                self._steer_cache = 0.0
            self._steer_cache += steer_increment

        elif abs(self._steer_cache) <= steer_return:
            self._steer_cache = 0.0

        elif self._steer_cache > 0.0:
            self._steer_cache -= steer_return

        else:
            self._steer_cache += steer_return

        self._steer_cache = clamp(
            self._steer_cache,
            -0.7,
            0.7,
        )
        self._control.steer = round(
            self._steer_cache,
            3,
        )
        self._control.hand_brake = bool(keys[K_SPACE])

    def _parse_walker_keys(self, keys, milliseconds, world):
        if not isinstance(self._control, carla.WalkerControl):
            return

        speed = 0.0

        if keys[K_LEFT] or keys[K_a]:
            speed = 0.01
            self._rotation.yaw -= 0.08 * milliseconds

        if keys[K_RIGHT] or keys[K_d]:
            speed = 0.01
            self._rotation.yaw += 0.08 * milliseconds

        if keys[K_UP] or keys[K_w]:
            if pygame.key.get_mods() & KMOD_SHIFT:
                speed = world.player_max_speed_fast
            else:
                speed = world.player_max_speed

        self._rotation.yaw = round(self._rotation.yaw, 1)

        self._control = carla.WalkerControl(
            direction=self._rotation.get_forward_vector(),
            speed=speed,
            jump=bool(keys[K_SPACE]),
        )

    @staticmethod
    def _is_quit_shortcut(key):
        return key == K_ESCAPE or (key == K_q and pygame.key.get_mods() & KMOD_CTRL)


class HUD:
    def __init__(self, width, height):
        self.dim = (width, height)

        notification_font = pygame.font.Font(
            pygame.font.get_default_font(),
            20,
        )

        font_name = "courier" if os.name == "nt" else "mono"
        fonts = [name for name in pygame.font.get_fonts() if font_name in name]

        if not fonts:
            fonts = pygame.font.get_fonts()

        preferred_font = "ubuntumono" if "ubuntumono" in fonts else fonts[0]
        mono = pygame.font.match_font(preferred_font)

        self._font_mono = pygame.font.Font(
            mono,
            12 if os.name == "nt" else 14,
        )
        self._notifications = FadingText(
            notification_font,
            (width, 40),
            (0, height - 40),
        )
        self.help = HelpText(
            pygame.font.Font(mono, 16),
            width,
            height,
        )

        self.server_fps = 0.0
        self.frame = 0
        self.simulation_time = 0.0
        self._show_info = True
        self._info_text = []
        self._server_clock = pygame.time.Clock()

    def on_world_tick(self, timestamp):
        self._server_clock.tick()
        self.server_fps = self._server_clock.get_fps()
        self.frame = timestamp.frame
        self.simulation_time = timestamp.elapsed_seconds

    def tick(self, world, clock):
        self._notifications.tick(world, clock)

        if not self._show_info or world.player is None:
            return

        transform = world.player.get_transform()
        velocity = world.player.get_velocity()
        control = world.player.get_control()
        compass = world.imu_sensor.compass

        heading = "N" if compass > 270.5 or compass < 89.5 else ""
        heading += "S" if 90.5 < compass < 269.5 else ""
        heading += "E" if 0.5 < compass < 179.5 else ""
        heading += "W" if 180.5 < compass < 359.5 else ""

        collision_history = world.collision_sensor.get_collision_history()
        collision = [
            collision_history[index + self.frame - 200] for index in range(200)
        ]
        maximum_collision = max(1.0, max(collision))
        collision = [value / maximum_collision for value in collision]

        vehicles = world.world.get_actors().filter("vehicle.*")
        speed = 3.6 * math.sqrt(velocity.x**2 + velocity.y**2 + velocity.z**2)

        self._info_text = [
            f"Server:  {self.server_fps:16.0f} FPS",
            f"Client:  {clock.get_fps():16.0f} FPS",
            "",
            (f"Vehicle: {get_actor_display_name(world.player, 20):>20}"),
            f"Map:     {world.map.name:>20}",
            (
                "Simulation time: "
                f"{str(datetime.timedelta(seconds=int(self.simulation_time))):>12}"
            ),
            "",
            f"Speed:   {speed:15.0f} km/h",
            f"Limit:   {world.args.speed_limit:15.0f} km/h",
            f"Compass: {compass:16.0f}\N{DEGREE SIGN} {heading:>2}",
            (
                "Accelero: "
                f"({world.imu_sensor.accelerometer[0]:5.1f},"
                f"{world.imu_sensor.accelerometer[1]:5.1f},"
                f"{world.imu_sensor.accelerometer[2]:5.1f})"
            ),
            (
                "Gyroscope:"
                f"({world.imu_sensor.gyroscope[0]:5.1f},"
                f"{world.imu_sensor.gyroscope[1]:5.1f},"
                f"{world.imu_sensor.gyroscope[2]:5.1f})"
            ),
            (f"Location: ({transform.location.x:7.2f}, {transform.location.y:7.2f})"),
            (f"GNSS: ({world.gnss_sensor.lat:10.6f}, {world.gnss_sensor.lon:11.6f})"),
            f"Height:  {transform.location.z:18.2f} m",
            "",
        ]

        if isinstance(control, carla.VehicleControl):
            self._info_text += [
                ("Throttle:", control.throttle, 0.0, 1.0),
                ("Steer:", control.steer, -1.0, 1.0),
                ("Brake:", control.brake, 0.0, 1.0),
                ("Reverse:", control.reverse),
                ("Hand brake:", control.hand_brake),
                ("Manual:", control.manual_gear_shift),
                (f"Gear:        { {-1: 'R', 0: 'N'}.get(control.gear, control.gear) }"),
            ]

        self._info_text += [
            "",
            "Collision:",
            collision,
            "",
            f"Number of vehicles: {len(vehicles):8d}",
        ]

        if len(vehicles) <= 1:
            return

        def distance(location):
            return math.sqrt(
                (location.x - transform.location.x) ** 2
                + (location.y - transform.location.y) ** 2
                + (location.z - transform.location.z) ** 2
            )

        nearby = [
            (distance(actor.get_location()), actor)
            for actor in vehicles
            if actor.id != world.player.id
        ]

        self._info_text.append("Nearby vehicles:")
        for actor_distance, actor in sorted(
            nearby,
            key=lambda item: item[0],
        ):
            if actor_distance > 200.0:
                break

            actor_name = get_actor_display_name(actor, 22)
            self._info_text.append(f"{actor_distance:4.0f}m {actor_name}")

    def toggle_info(self):
        self._show_info = not self._show_info

    def notification(self, text, seconds=2.0):
        self._notifications.set_text(text, seconds=seconds)

    def error(self, text):
        self._notifications.set_text(
            f"Error: {text}",
            color=(255, 0, 0),
        )

    def render(self, display):
        if self._show_info:
            info_surface = pygame.Surface((240, self.dim[1]))
            info_surface.set_alpha(100)
            display.blit(info_surface, (0, 0))

            vertical_offset = 4
            bar_horizontal_offset = 110
            bar_width = 106

            for item in self._info_text:
                if vertical_offset + 18 > self.dim[1]:
                    break

                if isinstance(item, list):
                    if len(item) > 1:
                        points = [
                            (
                                x + 8,
                                vertical_offset + 8 + (1.0 - float(y)) * 30,
                            )
                            for x, y in enumerate(item)
                        ]
                        pygame.draw.lines(
                            display,
                            (255, 136, 0),
                            False,
                            points,
                            2,
                        )

                    item = None
                    vertical_offset += 18

                elif isinstance(item, tuple):
                    if isinstance(item[1], bool):
                        rectangle = pygame.Rect(
                            (
                                bar_horizontal_offset,
                                vertical_offset + 8,
                            ),
                            (6, 6),
                        )
                        pygame.draw.rect(
                            display,
                            (255, 255, 255),
                            rectangle,
                            0 if item[1] else 1,
                        )
                    else:
                        border = pygame.Rect(
                            (
                                bar_horizontal_offset,
                                vertical_offset + 8,
                            ),
                            (bar_width, 6),
                        )
                        pygame.draw.rect(
                            display,
                            (255, 255, 255),
                            border,
                            1,
                        )

                        fraction = (float(item[1]) - float(item[2])) / (
                            float(item[3]) - float(item[2])
                        )
                        fraction = clamp(fraction, 0.0, 1.0)

                        if float(item[2]) < 0.0:
                            rectangle = pygame.Rect(
                                (
                                    bar_horizontal_offset + fraction * (bar_width - 6),
                                    vertical_offset + 8,
                                ),
                                (6, 6),
                            )
                        else:
                            rectangle = pygame.Rect(
                                (
                                    bar_horizontal_offset,
                                    vertical_offset + 8,
                                ),
                                (fraction * bar_width, 6),
                            )

                        pygame.draw.rect(
                            display,
                            (255, 255, 255),
                            rectangle,
                        )

                    item = item[0]

                if item:
                    text_surface = self._font_mono.render(
                        str(item),
                        True,
                        (255, 255, 255),
                    )
                    display.blit(
                        text_surface,
                        (8, vertical_offset),
                    )

                vertical_offset += 18

        self._notifications.render(display)
        self.help.render(display)


class FadingText:
    def __init__(self, font, dimensions, position):
        self.font = font
        self.dimensions = dimensions
        self.position = position
        self.seconds_left = 0.0
        self.surface = pygame.Surface(
            self.dimensions,
            pygame.SRCALPHA,
        )

    def set_text(
        self,
        text,
        color=(255, 255, 255),
        seconds=2.0,
    ):
        text_texture = self.font.render(text, True, color)
        self.surface = pygame.Surface(
            self.dimensions,
            pygame.SRCALPHA,
        )
        self.seconds_left = seconds
        self.surface.blit(text_texture, (10, 11))

    def tick(self, _world, clock):
        delta_seconds = clock.get_time() / 1000.0
        self.seconds_left = max(
            0.0,
            self.seconds_left - delta_seconds,
        )
        alpha = int(clamp(500.0 * self.seconds_left, 0.0, 255.0))
        self.surface.set_alpha(alpha)

    def render(self, display):
        display.blit(self.surface, self.position)


class HelpText:
    def __init__(self, font, width, height):
        lines = (__doc__ or "").splitlines()

        self.font = font
        self.line_space = 18
        self.dimensions = (
            780,
            len(lines) * self.line_space + 24,
        )
        self.position = (
            width / 2 - self.dimensions[0] / 2,
            height / 2 - self.dimensions[1] / 2,
        )
        self.surface = pygame.Surface(
            self.dimensions,
            pygame.SRCALPHA,
        )
        self.surface.fill((0, 0, 0, 220))

        for line_number, line in enumerate(lines):
            texture = self.font.render(
                line,
                True,
                (255, 255, 255),
            )
            self.surface.blit(
                texture,
                (22, 12 + line_number * self.line_space),
            )

        self._render = False

    def toggle(self):
        self._render = not self._render

    def render(self, display):
        if self._render:
            display.blit(self.surface, self.position)


class CollisionSensor:
    def __init__(self, parent_actor, hud):
        self.sensor = None
        self.history = []
        self.parent = parent_actor
        self.hud = hud

        world = self.parent.get_world()
        blueprint = world.get_blueprint_library().find("sensor.other.collision")
        self.sensor = world.spawn_actor(
            blueprint,
            carla.Transform(),
            attach_to=self.parent,
        )

        weak_self = weakref.ref(self)
        self.sensor.listen(
            lambda event: CollisionSensor._on_collision(
                weak_self,
                event,
            )
        )

    def get_collision_history(self):
        history = collections.defaultdict(int)

        for frame, intensity in self.history:
            history[frame] += intensity

        return history

    @staticmethod
    def _on_collision(weak_self, event):
        self = weak_self()
        if self is None:
            return

        actor_type = get_actor_display_name(event.other_actor)
        self.hud.notification(f"Collision with {actor_type!r}")

        impulse = event.normal_impulse
        intensity = math.sqrt(impulse.x**2 + impulse.y**2 + impulse.z**2)
        self.history.append((event.frame, intensity))

        if len(self.history) > 4000:
            self.history.pop(0)


class LaneInvasionSensor:
    def __init__(self, parent_actor, hud):
        self.sensor = None
        self.parent = parent_actor
        self.hud = hud

        world = self.parent.get_world()
        blueprint = world.get_blueprint_library().find("sensor.other.lane_invasion")
        self.sensor = world.spawn_actor(
            blueprint,
            carla.Transform(),
            attach_to=self.parent,
        )

        weak_self = weakref.ref(self)
        self.sensor.listen(
            lambda event: LaneInvasionSensor._on_invasion(
                weak_self,
                event,
            )
        )

    @staticmethod
    def _on_invasion(weak_self, event):
        self = weak_self()
        if self is None:
            return

        lane_types = {marking.type for marking in event.crossed_lane_markings}
        descriptions = [repr(str(lane_type).split()[-1]) for lane_type in lane_types]
        self.hud.notification("Crossed line " + " and ".join(descriptions))


class GnssSensor:
    def __init__(self, parent_actor):
        self.sensor = None
        self.parent = parent_actor
        self.lat = 0.0
        self.lon = 0.0

        world = self.parent.get_world()
        blueprint = world.get_blueprint_library().find("sensor.other.gnss")
        transform = carla.Transform(carla.Location(x=1.0, z=2.8))
        self.sensor = world.spawn_actor(
            blueprint,
            transform,
            attach_to=self.parent,
        )

        weak_self = weakref.ref(self)
        self.sensor.listen(
            lambda event: GnssSensor._on_event(
                weak_self,
                event,
            )
        )

    @staticmethod
    def _on_event(weak_self, event):
        self = weak_self()
        if self is None:
            return

        self.lat = event.latitude
        self.lon = event.longitude


class IMUSensor:
    def __init__(self, parent_actor):
        self.sensor = None
        self.parent = parent_actor
        self.accelerometer = (0.0, 0.0, 0.0)
        self.gyroscope = (0.0, 0.0, 0.0)
        self.compass = 0.0

        world = self.parent.get_world()
        blueprint = world.get_blueprint_library().find("sensor.other.imu")
        self.sensor = world.spawn_actor(
            blueprint,
            carla.Transform(),
            attach_to=self.parent,
        )

        weak_self = weakref.ref(self)
        self.sensor.listen(
            lambda data: IMUSensor._on_event(
                weak_self,
                data,
            )
        )

    @staticmethod
    def _on_event(weak_self, data):
        self = weak_self()
        if self is None:
            return

        minimum, maximum = -99.9, 99.9

        self.accelerometer = (
            clamp(data.accelerometer.x, minimum, maximum),
            clamp(data.accelerometer.y, minimum, maximum),
            clamp(data.accelerometer.z, minimum, maximum),
        )
        self.gyroscope = (
            clamp(
                math.degrees(data.gyroscope.x),
                minimum,
                maximum,
            ),
            clamp(
                math.degrees(data.gyroscope.y),
                minimum,
                maximum,
            ),
            clamp(
                math.degrees(data.gyroscope.z),
                minimum,
                maximum,
            ),
        )
        self.compass = math.degrees(data.compass)


class RadarSensor:
    def __init__(self, parent_actor):
        self.sensor = None
        self.parent = parent_actor
        self.velocity_range = 7.5

        world = self.parent.get_world()
        self.debug = world.debug
        blueprint = world.get_blueprint_library().find("sensor.other.radar")
        blueprint.set_attribute("horizontal_fov", "35")
        blueprint.set_attribute("vertical_fov", "20")

        self.sensor = world.spawn_actor(
            blueprint,
            carla.Transform(
                carla.Location(x=2.8, z=1.0),
                carla.Rotation(pitch=5.0),
            ),
            attach_to=self.parent,
        )

        weak_self = weakref.ref(self)
        self.sensor.listen(
            lambda data: RadarSensor._on_event(
                weak_self,
                data,
            )
        )

    @staticmethod
    def _on_event(weak_self, radar_data):
        self = weak_self()
        if self is None:
            return

        current_rotation = radar_data.transform.rotation

        for detection in radar_data:
            azimuth = math.degrees(detection.azimuth)
            altitude = math.degrees(detection.altitude)
            forward_vector = carla.Vector3D(x=detection.depth - 0.25)

            carla.Transform(
                carla.Location(),
                carla.Rotation(
                    pitch=current_rotation.pitch + altitude,
                    yaw=current_rotation.yaw + azimuth,
                    roll=current_rotation.roll,
                ),
            ).transform(forward_vector)

            normalized_velocity = detection.velocity / self.velocity_range
            red = int(
                clamp(
                    1.0 - normalized_velocity,
                    0.0,
                    1.0,
                )
                * 255.0
            )
            green = int(
                clamp(
                    1.0 - abs(normalized_velocity),
                    0.0,
                    1.0,
                )
                * 255.0
            )
            blue = int(
                abs(
                    clamp(
                        -1.0 - normalized_velocity,
                        -1.0,
                        0.0,
                    )
                )
                * 255.0
            )

            self.debug.draw_point(
                radar_data.transform.location + forward_vector,
                size=0.075,
                life_time=0.06,
                persistent_lines=False,
                color=carla.Color(red, green, blue),
            )


class CameraManager:
    def __init__(self, parent_actor, hud, gamma_correction: float):
        self.sensor = None
        self.surface = None
        self.parent = parent_actor
        self.hud = hud
        self.recording = False
        self.index = None
        self.lidar_range = 50.0

        bound_y = 0.5 + self.parent.bounding_box.extent.y
        attachment = carla.AttachmentType
        spring_arm = spring_arm_attachment()

        self.camera_transforms = [
            (
                carla.Transform(
                    carla.Location(x=-5.5, z=2.5),
                    carla.Rotation(pitch=8.0),
                ),
                spring_arm,
            ),
            (
                carla.Transform(carla.Location(x=1.6, z=1.7)),
                attachment.Rigid,
            ),
            (
                carla.Transform(carla.Location(x=5.5, y=1.5, z=1.5)),
                spring_arm,
            ),
            (
                carla.Transform(
                    carla.Location(x=-8.0, z=6.0),
                    carla.Rotation(pitch=6.0),
                ),
                spring_arm,
            ),
            (
                carla.Transform(
                    carla.Location(
                        x=-1.0,
                        y=-bound_y,
                        z=0.5,
                    )
                ),
                attachment.Rigid,
            ),
        ]
        self.transform_index = 1

        self.sensors = [
            [
                "sensor.camera.rgb",
                cc.Raw,
                "Camera RGB",
                {},
            ],
            [
                "sensor.camera.depth",
                cc.Raw,
                "Camera Depth (Raw)",
                {},
            ],
            [
                "sensor.camera.depth",
                cc.Depth,
                "Camera Depth (Gray Scale)",
                {},
            ],
            [
                "sensor.camera.depth",
                cc.LogarithmicDepth,
                "Camera Depth (Logarithmic)",
                {},
            ],
            [
                "sensor.camera.semantic_segmentation",
                cc.Raw,
                "Semantic Segmentation (Raw)",
                {},
            ],
            [
                "sensor.camera.semantic_segmentation",
                cc.CityScapesPalette,
                "Semantic Segmentation (CityScapes)",
                {},
            ],
            [
                "sensor.lidar.ray_cast",
                None,
                "LiDAR",
                {"range": "50"},
            ],
            [
                "sensor.camera.dvs",
                cc.Raw,
                "Dynamic Vision Sensor",
                {},
            ],
            [
                "sensor.camera.rgb",
                cc.Raw,
                "Camera RGB Distorted",
                {
                    "lens_circle_multiplier": "3.0",
                    "lens_circle_falloff": "3.0",
                    "chromatic_aberration_intensity": "0.5",
                    "chromatic_aberration_offset": "0.0",
                },
            ],
        ]

        world = self.parent.get_world()
        blueprint_library = world.get_blueprint_library()

        for sensor_definition in self.sensors:
            sensor_type = sensor_definition[0]
            attributes = sensor_definition[3]
            blueprint = blueprint_library.find(sensor_type)

            if sensor_type.startswith("sensor.camera"):
                blueprint.set_attribute(
                    "image_size_x",
                    str(self.hud.dim[0]),
                )
                blueprint.set_attribute(
                    "image_size_y",
                    str(self.hud.dim[1]),
                )

                if blueprint.has_attribute("gamma"):
                    blueprint.set_attribute(
                        "gamma",
                        str(gamma_correction),
                    )

            for attribute_name, attribute_value in attributes.items():
                if blueprint.has_attribute(attribute_name):
                    blueprint.set_attribute(
                        attribute_name,
                        attribute_value,
                    )

                if attribute_name == "range":
                    self.lidar_range = float(attribute_value)

            sensor_definition.append(blueprint)

    def toggle_camera(self) -> None:
        self.transform_index = (self.transform_index + 1) % len(self.camera_transforms)
        self.set_sensor(
            self.index or 0,
            notify=False,
            force_respawn=True,
        )

    def set_sensor(
        self,
        index: int,
        notify: bool = True,
        force_respawn: bool = False,
    ) -> None:
        index %= len(self.sensors)

        needs_respawn = (
            self.index is None
            or force_respawn
            or self.sensors[index][0] != self.sensors[self.index][0]
            or self.sensors[index][2] != self.sensors[self.index][2]
        )

        if needs_respawn:
            safe_stop_and_destroy(self.sensor)
            self.sensor = None
            self.surface = None

            transform, attachment_type = self.camera_transforms[self.transform_index]
            sensor = self.parent.get_world().spawn_actor(
                self.sensors[index][-1],
                transform,
                attach_to=self.parent,
                attachment_type=attachment_type,
            )

            self.sensor = sensor
            self.index = index

            weak_self = weakref.ref(self)
            sensor.listen(
                lambda data, expected_sensor=sensor: CameraManager._parse_image(
                    weak_self,
                    data,
                    expected_sensor,
                )
            )
        else:
            self.index = index

        if notify:
            self.hud.notification(self.sensors[index][2])

    def next_sensor(self) -> None:
        self.set_sensor((self.index or 0) + 1)

    def toggle_recording(self) -> None:
        self.recording = not self.recording

        if self.recording:
            IMAGE_OUTPUT_DIRECTORY.mkdir(
                parents=True,
                exist_ok=True,
            )

        state = "On" if self.recording else "Off"
        self.hud.notification(f"Image recording {state}")

    def render(self, display: pygame.Surface) -> None:
        if self.surface is not None:
            display.blit(self.surface, (0, 0))

    @staticmethod
    def _parse_image(weak_self: weakref.ref, image, expected_sensor) -> None:
        self = weak_self()

        if self is None or self.sensor is not expected_sensor or self.index is None:
            return

        sensor_type = self.sensors[self.index][0]

        if sensor_type.startswith("sensor.lidar"):
            points = np.frombuffer(
                image.raw_data,
                dtype=np.float32,
            ).reshape((-1, 4))

            lidar_data = np.array(
                points[:, :2],
                copy=True,
            )
            lidar_data *= min(self.hud.dim) / (2.0 * self.lidar_range)
            lidar_data += (
                self.hud.dim[0] * 0.5,
                self.hud.dim[1] * 0.5,
            )
            lidar_data = np.rint(lidar_data).astype(np.int32)

            valid = (
                (lidar_data[:, 0] >= 0)
                & (lidar_data[:, 0] < self.hud.dim[0])
                & (lidar_data[:, 1] >= 0)
                & (lidar_data[:, 1] < self.hud.dim[1])
            )
            lidar_data = lidar_data[valid]

            lidar_image = np.zeros(
                (
                    self.hud.dim[0],
                    self.hud.dim[1],
                    3,
                ),
                dtype=np.uint8,
            )

            if lidar_data.size:
                lidar_image[
                    lidar_data[:, 0],
                    lidar_data[:, 1],
                ] = (255, 255, 255)

            self.surface = pygame.surfarray.make_surface(lidar_image)

        elif sensor_type.startswith("sensor.camera.dvs"):
            event_dtype = np.dtype(
                [
                    ("x", np.uint16),
                    ("y", np.uint16),
                    ("t", np.int64),
                    ("pol", np.bool_),
                ]
            )
            events = np.frombuffer(
                image.raw_data,
                dtype=event_dtype,
            )

            valid = (events["x"] < image.width) & (events["y"] < image.height)
            events = events[valid]

            dvs_image = np.zeros(
                (image.height, image.width, 3),
                dtype=np.uint8,
            )
            channels = np.where(events["pol"], 2, 0)

            dvs_image[
                events["y"],
                events["x"],
                channels,
            ] = 255

            self.surface = pygame.surfarray.make_surface(
                np.ascontiguousarray(dvs_image.swapaxes(0, 1))
            )

        else:
            image.convert(self.sensors[self.index][1])

            array = np.frombuffer(
                image.raw_data,
                dtype=np.uint8,
            )
            array = array.reshape((image.height, image.width, 4))
            rgb = array[:, :, :3][:, :, ::-1]
            rgb = np.ascontiguousarray(rgb.swapaxes(0, 1))
            self.surface = pygame.surfarray.make_surface(rgb)

        if self.recording:
            IMAGE_OUTPUT_DIRECTORY.mkdir(
                parents=True,
                exist_ok=True,
            )
            image.save_to_disk(str(IMAGE_OUTPUT_DIRECTORY / f"{image.frame:08d}"))


def game_loop(args: argparse.Namespace) -> None:
    pygame.init()
    pygame.font.init()

    client = None
    world = None

    try:
        client = carla.Client(args.host, args.port)
        client.set_timeout(args.timeout)

        pygame.display.set_caption("CARLA 0.10 Manual Control")
        display = pygame.display.set_mode(
            (args.width, args.height),
            pygame.DOUBLEBUF,
        )

        hud = HUD(args.width, args.height)
        world = World(client.get_world(), hud, args)
        controller = KeyboardControl(
            world,
            args.autopilot,
        )

        clock = pygame.time.Clock()

        while True:
            clock.tick_busy_loop(args.fps)

            if controller.parse_events(
                client,
                world,
                clock,
            ):
                return

            world.tick(clock)
            world.render(display)
            pygame.display.flip()

    finally:
        if client is not None and world is not None and world.recording_enabled:
            try:
                client.stop_recorder()
            except RuntimeError:
                pass

        if world is not None:
            world.destroy()

        pygame.quit()


def parse_resolution(parser: argparse.ArgumentParser, value: str) -> tuple[int, int]:
    match = re.fullmatch(
        r"(\d+)[xX](\d+)",
        value.strip(),
    )

    if match is None:
        parser.error("--res must use WIDTHxHEIGHT format, for example 1280x720")

    width = int(match.group(1))
    height = int(match.group(2))

    if width <= 0 or height <= 0:
        parser.error("Resolution dimensions must be positive.")

    return width, height


def main():
    parser = argparse.ArgumentParser(
        description=("CARLA 0.10 manual keyboard control client")
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        dest="debug",
        help="Enable debug logging.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="CARLA server address (default: 127.0.0.1).",
    )
    parser.add_argument(
        "-p",
        "--port",
        default=2000,
        type=int,
        help="CARLA server port (default: 2000).",
    )
    parser.add_argument(
        "--timeout",
        default=10.0,
        type=float,
        help="Client timeout in seconds (default: 10).",
    )
    parser.add_argument(
        "-a",
        "--autopilot",
        action="store_true",
        help="Start with autopilot enabled.",
    )
    parser.add_argument(
        "--res",
        default="1280x720",
        help="Window resolution (default: 1280x720).",
    )
    parser.add_argument(
        "--fps",
        default=60,
        type=int,
        help="Maximum client FPS (default: 60).",
    )
    parser.add_argument(
        "--filter",
        default="vehicle.*",
        help='Actor filter (default: "vehicle.*").',
    )
    parser.add_argument(
        "--generation",
        default="all",
        help='Actor generation, such as 1, 2, or "all".',
    )
    parser.add_argument(
        "--rolename",
        default="hero",
        help='Actor role name (default: "hero").',
    )
    parser.add_argument(
        "--gamma",
        default=2.2,
        type=float,
        help="Camera gamma correction (default: 2.2).",
    )
    parser.add_argument(
        "--x",
        type=float,
        help="Custom spawn X coordinate.",
    )
    parser.add_argument(
        "--y",
        type=float,
        help="Custom spawn Y coordinate.",
    )
    parser.add_argument(
        "--z",
        type=float,
        help="Custom spawn Z coordinate.",
    )
    parser.add_argument(
        "--roll",
        type=float,
        default=0.0,
        help="Custom spawn roll in degrees.",
    )
    parser.add_argument(
        "--pitch",
        type=float,
        default=0.0,
        help="Custom spawn pitch in degrees.",
    )
    parser.add_argument(
        "--yaw",
        type=float,
        default=0.0,
        help="Custom spawn yaw in degrees.",
    )
    parser.add_argument(
        "-s",
        "--speed-limit",
        "--speed_limit",
        dest="speed_limit",
        default=50.0,
        type=float,
        help=("Manual driving speed limit in km/h (default: 50)."),
    )

    args = parser.parse_args()
    args.width, args.height = parse_resolution(
        parser,
        args.res,
    )

    if args.port <= 0 or args.port > 65535:
        parser.error("--port must be between 1 and 65535.")

    if args.timeout <= 0.0:
        parser.error("--timeout must be greater than zero.")

    if args.fps <= 0:
        parser.error("--fps must be greater than zero.")

    if args.speed_limit <= 0.0:
        parser.error("--speed-limit must be greater than zero.")

    provided_coordinates = sum(value is not None for value in (args.x, args.y, args.z))
    if provided_coordinates not in (0, 3):
        parser.error("--x, --y, and --z must be supplied together.")

    logging.basicConfig(
        format="%(levelname)s: %(message)s",
        level=logging.DEBUG if args.debug else logging.INFO,
    )
    logging.info(
        "Connecting to CARLA server at %s:%s",
        args.host,
        args.port,
    )

    print(__doc__)

    try:
        game_loop(args)
    except KeyboardInterrupt:
        print("\nCancelled by user. Bye!")
    except RuntimeError as error:
        logging.error("%s", error)
        if args.debug:
            raise


if __name__ == "__main__":
    main()
