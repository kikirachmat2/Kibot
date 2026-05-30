#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${1:-android/KiBotMonitor}"

fail() {
  echo "FAIL:$1"
  exit 1
}

[ -d "$ROOT_DIR" ] || fail "missing_project_dir"
[ -f "$ROOT_DIR/settings.gradle.kts" ] || fail "missing_settings_gradle"
[ -f "$ROOT_DIR/build.gradle.kts" ] || fail "missing_root_build_gradle"
[ -f "$ROOT_DIR/gradle.properties" ] || fail "missing_gradle_properties"
[ -f "$ROOT_DIR/app/build.gradle.kts" ] || fail "missing_app_build_gradle"
[ -f "$ROOT_DIR/app/src/main/AndroidManifest.xml" ] || fail "missing_manifest"
[ -f "$ROOT_DIR/app/src/main/java/id/kibot/monitor/MainActivity.kt" ] || fail "missing_main_activity"
[ -f "$ROOT_DIR/app/src/main/java/id/kibot/monitor/data/KiBotApi.kt" ] || fail "missing_api"
[ -f "$ROOT_DIR/app/src/main/java/id/kibot/monitor/data/KiBotModels.kt" ] || fail "missing_models"
[ -f "$ROOT_DIR/app/src/main/java/id/kibot/monitor/data/KiBotRepository.kt" ] || fail "missing_repository"
[ -f "$ROOT_DIR/app/src/main/java/id/kibot/monitor/data/SettingsStore.kt" ] || fail "missing_settings"
[ -f "$ROOT_DIR/app/src/main/java/id/kibot/monitor/worker/KiBotSyncWorker.kt" ] || fail "missing_worker"
[ -f "$ROOT_DIR/app/src/main/java/id/kibot/monitor/service/KiBotMonitoringService.kt" ] || fail "missing_service"
[ -f "$ROOT_DIR/app/src/main/java/id/kibot/monitor/widget/KiBotStatusWidgetProvider.kt" ] || fail "missing_widget_provider"
[ -f "$ROOT_DIR/app/src/main/java/id/kibot/monitor/widget/KiBotWidgetUpdateReceiver.kt" ] || fail "missing_widget_receiver"
[ -f "$ROOT_DIR/app/src/main/java/id/kibot/monitor/widget/BootReceiver.kt" ] || fail "missing_boot_receiver"
[ -f "$ROOT_DIR/app/src/main/res/xml/kibot_status_widget_info.xml" ] || fail "missing_widget_xml"
[ -f "$ROOT_DIR/app/src/main/res/layout/widget_status.xml" ] || fail "missing_widget_layout"

grep -RIn "id.kibot.monitor" "$ROOT_DIR/app/src/main" >/dev/null || fail "missing_package_id"
grep -RIn "INTERNET" "$ROOT_DIR/app/src/main/AndroidManifest.xml" >/dev/null || fail "missing_internet_permission"
grep -RIn "POST_NOTIFICATIONS" "$ROOT_DIR/app/src/main/AndroidManifest.xml" >/dev/null || fail "missing_notifications_permission"
grep -RIn "FOREGROUND_SERVICE" "$ROOT_DIR/app/src/main/AndroidManifest.xml" >/dev/null || fail "missing_foreground_permission"
grep -RIn "RECEIVE_BOOT_COMPLETED" "$ROOT_DIR/app/src/main/AndroidManifest.xml" >/dev/null || fail "missing_boot_permission"

echo "OK:ANDROID_PROJECT_READY"
