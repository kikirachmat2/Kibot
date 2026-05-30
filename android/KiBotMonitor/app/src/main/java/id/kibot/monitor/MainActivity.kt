package id.kibot.monitor

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import id.kibot.monitor.ui.KiBotApp
import id.kibot.monitor.ui.KiBotDashboardViewModel
import id.kibot.monitor.ui.KiBotTheme

class MainActivity : ComponentActivity() {
  private val viewModel: KiBotDashboardViewModel by viewModels()

  override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)
    setContent {
      KiBotTheme {
        KiBotApp(viewModel = viewModel)
      }
    }
  }
}
