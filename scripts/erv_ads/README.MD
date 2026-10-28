# Pre-req
 - 

# 1. Exec into the dt-core container
	dt exec

# 2. cd into erv_ads
	cd distributed-testing/scripts/erv_ads

# 3. run setup.sh
	./setup.sh

	**if you need to spawn the ERV**
	python3 dt/spawn_erv_actor.py --role PATH-M-1 --pose 66.959,-127.476,7.17,-70.93
	
# 4. Update IP address in relay.sh
	Lines 13,14,15
	BIND=${RELAY_BIND:-<your ip>:5398}
	TO=${RELAY_TO:-<your ip>:47347}
	CARLA=${RELAY_CARLA:-<your ip>:2000}

# 5. Spawn the car
	python3 dt/dt_event3_ego.py --role VW-M-1 --erv-role PATH-M-1 --spawn-only

# 6. Make it so that the car can communicate with TENA
	bash dt/relay.sh on

# 7. Make the car approach the ERV
	python3 dt/dt_event3_ego.py --role VW-M-1 --erv-role PATH-M-1 --attach --record --tag run1 --set evidence.out_dir=/tmp/runs

# 8. reset the car
	python3 dt/repark_ego.py --role VW-M-1 --erv-role PATH-M-1

