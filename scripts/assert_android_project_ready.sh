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
[ -f "$ROOT_DIR/app/src/main/java/id/kibot/monitor/widget/KiBotActionReceiver.kt" ] || fail "missing_action_receiver"
[ -f "$ROOT_DIR/app/src/main/java/id/kibot/monitor/widget/KiBotWidgetUpdateReceiver.kt" ] || fail "missing_widget_receiver"
[ -f "$ROOT_DIR/app/src/main/java/id/kibot/monitor/widget/BootReceiver.kt" ] || fail "missing_boot_receiver"
[ -f "$ROOT_DIR/app/src/main/res/drawable/kibot_logo.png" ] || fail "missing_kibot_icon"
[ -f "$ROOT_DIR/app/src/main/res/drawable/ic_launcher_background.xml" ] || fail "missing_icon_background"
[ -f "$ROOT_DIR/app/src/main/res/mipmap-anydpi-v26/ic_launcher.xml" ] || fail "missing_icon_xml"
[ -f "$ROOT_DIR/app/src/main/res/mipmap-anydpi-v26/ic_launcher_round.xml" ] || fail "missing_icon_round_xml"
[ -f "$ROOT_DIR/app/src/main/res/layout/widget_kibot_status.xml" ] || fail "missing_widget_layout"
[ -f "$ROOT_DIR/app/src/main/res/xml/kibot_status_widget_info.xml" ] || fail "missing_widget_xml"

grep -RIn "id.kibot.monitor" "$ROOT_DIR/app/src/main" >/dev/null || fail "missing_package_id"
grep -RIn 'KiBot' "$ROOT_DIR/app/src/main/res/values/strings.xml" >/dev/null || fail "missing_app_name"
grep -RIn 'KiBot Status 5x2' "$ROOT_DIR/app/src/main/res/values/strings.xml" >/dev/null || fail "missing_widget_name"
grep -RIn 'android:icon="@mipmap/ic_launcher"' "$ROOT_DIR/app/src/main/AndroidManifest.xml" >/dev/null || fail "manifest_icon_wrong"
grep -RIn 'android:roundIcon="@mipmap/ic_launcher_round"' "$ROOT_DIR/app/src/main/AndroidManifest.xml" >/dev/null || fail "manifest_round_icon_wrong"
grep -RIn 'android:label="@string/app_name"' "$ROOT_DIR/app/src/main/AndroidManifest.xml" >/dev/null || fail "manifest_label_wrong"
grep -RIn 'targetCellWidth="5"' "$ROOT_DIR/app/src/main/res/xml/kibot_status_widget_info.xml" >/dev/null || fail "widget_cell_width_wrong"
grep -RIn 'targetCellHeight="2"' "$ROOT_DIR/app/src/main/res/xml/kibot_status_widget_info.xml" >/dev/null || fail "widget_cell_height_wrong"
grep -RIn 'minWidth="320dp"' "$ROOT_DIR/app/src/main/res/xml/kibot_status_widget_info.xml" >/dev/null || fail "widget_min_width_wrong"
grep -RIn 'minHeight="110dp"' "$ROOT_DIR/app/src/main/res/xml/kibot_status_widget_info.xml" >/dev/null || fail "widget_min_height_wrong"
grep -RIn 'KiBot Monitor' "$ROOT_DIR/app/src/main" >/dev/null && fail "old_app_name_visible"
grep -RIn "INTERNET" "$ROOT_DIR/app/src/main/AndroidManifest.xml" >/dev/null || fail "missing_internet_permission"
grep -RIn "POST_NOTIFICATIONS" "$ROOT_DIR/app/src/main/AndroidManifest.xml" >/dev/null || fail "missing_notifications_permission"
grep -RIn "FOREGROUND_SERVICE" "$ROOT_DIR/app/src/main/AndroidManifest.xml" >/dev/null || fail "missing_foreground_permission"
grep -RIn "RECEIVE_BOOT_COMPLETED" "$ROOT_DIR/app/src/main/AndroidManifest.xml" >/dev/null || fail "missing_boot_permission"
grep -RIn '/api/control-plane' "$ROOT_DIR/app/src/main" >/dev/null || fail "missing_control_plane_api"

echo "OK:ANDROID_PROJECT_READY"
