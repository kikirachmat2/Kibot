# 📱 KiBot Support: Android APK Tools

Build and deployment pipeline for the KiBot Android monitoring application.

## Responsibility
- **Mobile Oversight**: Facilitating the deployment of the KiBot mobile app for real-time alerts and on-the-go status checks.
- **Automation**: High-efficiency scripts for building, signing, and installing the APK via ADB (Android Debug Bridge).
- **Mesh Connectivity**: Tools to ensure secure communication between the mobile device and the Trinity cluster.

## Key Scripts
- `build_android_release.sh`: Orchestrates the full Gradle build process for the production release APK.
- `install_android_release.sh`: Automates the installation and patching of the APK to a connected Android device.
- `connect_android_wifi.sh`: Utility to setup and stabilize wireless ADB connections for wire-free debugging and deployment.
- `setup_android_sdk.sh`: Ensures the local environment has the necessary SDK tools and build dependencies.
