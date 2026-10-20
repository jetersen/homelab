{ pkgs ? import <nixpkgs> { config = { allowUnfree = true; android_sdk.accept_license = true; }; } }:
let
  sdk = (pkgs.androidenv.composeAndroidPackages {
    platformVersions = [ "34" ];
    buildToolsVersions = [ "34.0.0" ];
    includeCmake = false;
  }).androidsdk;
in pkgs.mkShell {
  packages = [ sdk pkgs.jdk17 ];
  ANDROID_SDK_ROOT = "${sdk}/libexec/android-sdk";
}
