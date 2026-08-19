// Builds dt-v2xhub with no git submodules and no leftover intermediate images.
//
// V2X-Hub is public: v2xhub-build-environment/v2xhub-full fetch its Dockerfile straight from
// GitHub at a pinned commit (output=cacheonly, so neither becomes an image of its own). The plugin
// repo is private and can't use the same trick -- GIT_AUTH_TOKEN secrets only authenticate a
// target's *primary* context, not a named one -- so it's git-cloned inside dt-v2xhub_Dockerfile
// with a mounted secret instead (see tena-v2xhub-plugin-build there).
//
// `dt-v2xhub` below is a group, not a target (the real final-image target is dt-v2xhub-image), so
// building it also builds tena-v2xhub-build-dependencies (the devcontainer stage) off the same
// shared graph for close to free.
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
  default = "dev"
}

variable "J2735_VERSION" {
  default = "2024"
}

variable "DT_BUILD_GENERAL_TAG" {
  default = "0.1.1"
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

target "v2xhub-full" {
  context    = "${V2XHUB_REPO}#${V2XHUB_REF}"
  dockerfile = "Dockerfile"
  target     = "v2xhub"
  output     = ["type=cacheonly"]
}

target "dt-v2xhub-image" {
  context    = ".."
  dockerfile = "dt-v2xhub_Dockerfile"
  contexts = {
    v2xhub-build-dependencies = "target:v2xhub-build-environment"
    v2xhub-default-runtime    = "target:v2xhub-full"
    tena-source                = "docker-image://harbor.distributedtesting.org/dot-ostr-dt/dt-build-general:${DT_BUILD_GENERAL_TAG}"
  }
  args = {
    J2735_VERSION = J2735_VERSION
    VERSION       = VERSION
    PLUGIN_REPO   = PLUGIN_REPO
    PLUGIN_REF    = PLUGIN_REF
  }
  secret = ["id=GIT_AUTH_TOKEN,src=../usdotfhwastol_token"]
  output = ["type=docker"]
  tags   = ["harbor.distributedtesting.org/dot-ostr-dt/dt-v2xhub:${VERSION}"]
}

// Devcontainer stage on its own: TENA + the tmx/ SDK, no plugin baked in. Tagged with V2X-Hub's
// own ref for traceability back to versions.env.
target "tena-v2xhub-build-dependencies" {
  inherits = ["dt-v2xhub-image"]
  target   = "tena-v2xhub-build-dependencies"
  output   = ["type=docker"]
  tags     = ["harbor.distributedtesting.org/dot-ostr-dt/dt-build-v2xhub:${V2XHUB_REF}"]
}
