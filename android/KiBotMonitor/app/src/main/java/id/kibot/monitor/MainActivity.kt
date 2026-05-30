package id.kibot.monitor

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Modifier
import androidx.lifecycle.lifecycleScope
import id.kibot.monitor.data.KiBotRepository
import id.kibot.monitor.ui.KiBotApp
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
  override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)
    setContent {
      MaterialTheme {
        Surface(modifier = Modifier) {
          LaunchedEffect(Unit) {
            lifecycleScope.launch { KiBotRepository(this@MainActivity).refreshNow() }
          }
          KiBotApp()
        }
      }
    }
  }
}
