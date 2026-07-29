# build

Dockerfiles and build scripts for the dt-* images.

**Main entry point: `build-image.sh`** — builds any image by name (see `./build-image.sh --help`).
Following tree shows which script uses which files.

```text
build-image.sh                            # main entry point; dispatches to one Dockerfile below
├── usdotfhwastol_token                   # secret file, mounted for build-general and v2xhub
├── build-assets.env/build-assets_*.env   # sets BUILD_DIR; sourced for base, core, v2xhub
│   └── (populated by fetch-assets.sh, which needs to be run manually beforehand)
│
├── dt-base_Dockerfile               # FROM ubuntu:22.04
│   ├── dt-build-general_Dockerfile  # FROM dt-base
│   │   └── dt-build-carla_Dockerfile  # FROM dt-build-general
│   └── dt-core_Dockerfile           # FROM dt-base
│       └── lib/COPY                 # copied in
│
├── dt-v2xhub_Dockerfile             # FROM dt-build-v2xhub (external, hand-committed image; see file header)
│   ├── checkout.bash                # copied in, clones vug-v2xhub-v2x-plugin using USDOTFHWASTOL_TOKEN
│   └── stages: assets -> base -> runtime (default)
│       # "base" has TENA/DIST installed but no plugin baked in - always builds even if the
│       # plugin is broken. Build it directly with `./build-image.sh v2xhub -v DEV --target base`
│       # for a devcontainer; mount your local plugin checkout in and build/debug interactively.
│       # "runtime" (the default target) additionally clones and builds the plugin - this is
│       # the deployable dt-v2xhub image, and only builds when the plugin builds cleanly.
│
├── dt-carla_Dockerfile              # FROM carlasim/carla:0.9.10
│   └── lib/MAPS, lib/CARLA_TFHRC, lib/COPY   # mounted/copied in
│
└── dt-carla-0-9-15_Dockerfile       # FROM carlasim/carla:0.9.15
    └── lib/MAPS_915, lib/COPY       # mounted/copied in
```

NOTE: Each `dt-*_Dockerfile` also documents its own raw `docker build` command at the top, in case you need to build it directly without the wrapper
