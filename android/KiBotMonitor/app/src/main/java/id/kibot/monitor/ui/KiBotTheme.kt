package id.kibot.monitor.ui

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.ui.unit.dp

private val DarkScheme = darkColorScheme(
  primary = Color(0xFF4ADE80),
  onPrimary = Color(0xFF04130B),
  secondary = Color(0xFF60A5FA),
  tertiary = Color(0xFFA78BFA),
  background = Color(0xFF08111F),
  onBackground = Color(0xFFE5E7EB),
  surface = Color(0xFF0F172A),
  onSurface = Color(0xFFE5E7EB),
  surfaceVariant = Color(0xFF17233A),
  onSurfaceVariant = Color(0xFFCBD5E1),
  error = Color(0xFFF97316),
)

private val LightScheme = lightColorScheme(
  primary = Color(0xFF0F766E),
  onPrimary = Color(0xFFFFFFFF),
  secondary = Color(0xFF2563EB),
  tertiary = Color(0xFF7C3AED),
  background = Color(0xFFF4F7FB),
  onBackground = Color(0xFF0F172A),
  surface = Color(0xFFFFFFFF),
  onSurface = Color(0xFF0F172A),
  surfaceVariant = Color(0xFFE5EEF8),
  onSurfaceVariant = Color(0xFF334155),
  error = Color(0xFFDC2626),
)

@Composable
fun KiBotTheme(content: @Composable () -> Unit) {
  val context = LocalContext.current
  val darkTheme = isSystemInDarkTheme()
  val colorScheme = when {
    Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && darkTheme -> dynamicDarkColorScheme(context)
    Build.VERSION.SDK_INT >= Build.VERSION_CODES.S -> dynamicLightColorScheme(context)
    darkTheme -> DarkScheme
    else -> LightScheme
  }

  MaterialTheme(
    colorScheme = colorScheme,
    typography = Typography(),
    shapes = Shapes(
      extraSmall = RoundedCornerShape(12.dp),
      small = RoundedCornerShape(16.dp),
      medium = RoundedCornerShape(20.dp),
      large = RoundedCornerShape(24.dp),
      extraLarge = RoundedCornerShape(28.dp),
    ),
    content = content,
  )
}
