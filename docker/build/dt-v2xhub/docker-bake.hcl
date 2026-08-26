// Builds dt-v2xhub without editing V2X-Hub's own Dockerfile: TenaV2XPlugin is injected as a native
// v2i-hub plugin, so their own unmodified ./build.sh compiles it alongside their own plugins.
//
// V2X-Hub's Dockerfile chains build-environment -> dependencies (runs ./build.sh) -> v2xhub (final
// image). dt-v2xhub-image runs that real Dockerfile at "v2xhub", with a `contexts` override
// redirecting their `build-environment` stage to tena-v2xhub-build-dependencies -- our own build of
// that same stage, plus TENA, plus the plugin's source dropped into src/v2i-hub/. Their own
// "dependencies" and "v2xhub" stages then run unmodified on top of that.
//
// `dt-v2xhub` is a group, not a target (the real final-image target is dt-v2xhub-image), so building
// it also builds tena-v2xhub-build-dependencies (the devcontainer image) for close to free.
//
// Usage (source versions.env first so its values, not the defaults below, get built):
//   set -a && source versions.env && set +a
//   docker buildx bake --allow=fs.read=.. dt-v2xhub

variable "V2XHUB_REPO" {
  default = "https://github.com/usdot-fhwa-OPS/V2X-Hub.git"
}

variable "V2XHUB_REF" {
  default = "develop"
}

variable "PLUGIN_REPO" {
  default = "https://github.com/usdot-fhwa-stol/vug-v2xhub-v2x-plugin.git"
}

variable "PLUGIN_REF" {
  default = "develop"
}

variable "VERSION" {
  default = "develop"
}

variable "J2735_VERSION" {
  default = "2024"
}

variable "DT_BUILD_GENERAL_TAG" {
  default = "dev-latest"
}

variable "TENA_VERSION" {
  default = "6.0.11"
}

group "dt-v2xhub" {
  targets = ["dt-v2xhub-image", "tena-v2xhub-build-dependencies"]
}

target "v2xhub-build-environment" {
  context    = "${V2XHUB_REPO}#${V2XHUB_REF}"
  dockerfile = "Dockerfile"
  target     = "build-environment"
  output     = ["type=cacheonly"]
}

// V2X-Hub's own build-environment stage plus TENA plus TenaV2XPlugin's source. Doubles as the
// devcontainer image (bind-mount the plugin source over the injected copy, build interactively) and
// as what dt-v2xhub-image substitutes in for V2X-Hub's own build-environment.
target "tena-v2xhub-build-dependencies" {
  context    = ".."
  dockerfile = "dt-v2xhub_Dockerfile"
  contexts = {
    v2xhub-build-dependencies = "target:v2xhub-build-environment"
    tena-source                = "docker-image://harbor.distributedtesting.org/distributed-testing-dev/dt-build-general:${DT_BUILD_GENERAL_TAG}"
  }
  args = {
    J2735_VERSION = J2735_VERSION
    TENA_VERSION  = TENA_VERSION
    PLUGIN_REPO   = PLUGIN_REPO
    PLUGIN_REF    = PLUGIN_REF
  }
  secret = ["id=GIT_AUTH_TOKEN,src=../usdotfhwastol_token"]
  output = ["type=docker"]
  tags   = ["harbor.distributedtesting.org/distributed-testing-dev/dt-build-v2xhub:${V2XHUB_REF}"]
}

// V2X-Hub's own, unmodified Dockerfile, run at its "v2xhub" stage, with `build-environment`
// redirected to tena-v2xhub-build-dependencies above.
target "dt-v2xhub-image" {
  context    = "${V2XHUB_REPO}#${V2XHUB_REF}"
  dockerfile = "Dockerfile"
  target     = "v2xhub"
  contexts = {
    "build-environment" = "target:tena-v2xhub-build-dependencies"
  }
  args = {
    VERSION = VERSION
  }
  output = ["type=docker"]
  tags   = ["harbor.distributedtesting.org/distributed-testing-dev/dt-v2xhub:${VERSION}"]
}
