#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${1:-android/KiBotMonitor}"

fail() {
  echo "FAIL:$1"
  exit 1
}

[ -f "$ROOT_DIR/app/src/main/res/drawable/kibot_logo.png" ] || fail "missing_icon_png"
[ -f "$ROOT_DIR/app/src/main/java/id/kibot/monitor/data/KiBotApi.kt" ] || fail "missing_api"
[ -f "$ROOT_DIR/app/src/main/java/id/kibot/monitor/data/KiBotModels.kt" ] || fail "missing_models"
[ -f "$ROOT_DIR/app/src/main/java/id/kibot/monitor/data/KiBotRepository.kt" ] || fail "missing_repository"
[ -f "$ROOT_DIR/app/src/main/java/id/kibot/monitor/ui/KiBotApp.kt" ] || fail "missing_ui"
[ -f "$ROOT_DIR/app/src/main/java/id/kibot/monitor/ui/KiBotDashboardViewModel.kt" ] || fail "missing_viewmodel"
[ -f "$ROOT_DIR/app/src/main/java/id/kibot/monitor/ui/KiBotTheme.kt" ] || fail "missing_theme"
[ -f "$ROOT_DIR/app/src/main/java/id/kibot/monitor/service/KiBotMonitoringService.kt" ] || fail "missing_service"
[ -f "$ROOT_DIR/app/src/main/java/id/kibot/monitor/widget/KiBotStatusWidgetProvider.kt" ] || fail "missing_widget"
[ -f "$ROOT_DIR/app/src/main/res/layout/widget_kibot_status.xml" ] || fail "missing_widget_layout"

grep -RIn 'KiBot' "$ROOT_DIR/app/src/main/res/values/strings.xml" >/dev/null || fail "app_name_wrong"
grep -RIn 'KiBot Status 5x2' "$ROOT_DIR/app/src/main/res/values/strings.xml" >/dev/null || fail "widget_name_wrong"
grep -RIn 'android:targetCellWidth="5"' "$ROOT_DIR/app/src/main/res/xml/kibot_status_widget_info.xml" >/dev/null || fail "widget_width_wrong"
grep -RIn 'android:targetCellHeight="2"' "$ROOT_DIR/app/src/main/res/xml/kibot_status_widget_info.xml" >/dev/null || fail "widget_height_wrong"
grep -RIn 'android:minWidth="320dp"' "$ROOT_DIR/app/src/main/res/xml/kibot_status_widget_info.xml" >/dev/null || fail "widget_min_width_wrong"
grep -RIn 'android:minHeight="110dp"' "$ROOT_DIR/app/src/main/res/xml/kibot_status_widget_info.xml" >/dev/null || fail "widget_min_height_wrong"
grep -RIn '/api/control-plane' "$ROOT_DIR/app/src/main/java" >/dev/null || fail "missing_api_call"
grep -RIn 'fetchControlPlane' "$ROOT_DIR/app/src/main/java/id/kibot/monitor/data/KiBotRepository.kt" >/dev/null || fail "repository_not_fetching"
grep -RIn 'monitoringEnabled' "$ROOT_DIR/app/src/main/java/id/kibot/monitor/data/SettingsStore.kt" >/dev/null || fail "settings_missing_monitoring"
grep -RIn 'baseUrl' "$ROOT_DIR/app/src/main/java/id/kibot/monitor/data/SettingsStore.kt" >/dev/null || fail "settings_missing_base_url"
grep -RIn 'Ringkasan' "$ROOT_DIR/app/src/main/java/id/kibot/monitor/ui/KiBotApp.kt" >/dev/null || fail "ui_missing_tabs"
grep -RIn 'Pengaturan' "$ROOT_DIR/app/src/main/java/id/kibot/monitor/ui/KiBotApp.kt" >/dev/null || fail "ui_missing_settings"
grep -RIn 'Widget refresh' "$ROOT_DIR/app/src/main/java/id/kibot/monitor/ui/KiBotApp.kt" >/dev/null || fail "ui_missing_widget_hint"
grep -RIn 'KiBotWidget' "$ROOT_DIR/app/src/main/java/id/kibot/monitor/widget" >/dev/null || fail "missing_widget_logs"
grep -RIn 'KiBotApi' "$ROOT_DIR/app/src/main/java/id/kibot/monitor/data/KiBotApi.kt" >/dev/null || fail "missing_api_logs"
grep -RIn 'KiBotRepository' "$ROOT_DIR/app/src/main/java/id/kibot/monitor/data/KiBotRepository.kt" >/dev/null || fail "missing_repository_logs"
grep -RIn 'KiBotWorker' "$ROOT_DIR/app/src/main/java/id/kibot/monitor/worker/KiBotSyncWorker.kt" >/dev/null || fail "missing_worker_logs"

echo "OK:ANDROID_APP_POLISH"
