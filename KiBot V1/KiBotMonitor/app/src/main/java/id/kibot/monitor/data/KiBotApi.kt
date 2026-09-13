package id.kibot.monitor.data

import android.util.Log
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.IOException
import java.util.concurrent.TimeUnit

data class KiBotFetchResult(
  val rawJson: String,
  val httpStatus: Int,
  val parsed: ParsedControlPlane,
)

class KiBotApi(
  private val baseUrl: String,
  private val authUsername: String = "",
  private val authPassword: String = "",
  private val client: OkHttpClient = OkHttpClient.Builder()
    .connectTimeout(10, TimeUnit.SECONDS)
    .readTimeout(10, TimeUnit.SECONDS)
    .writeTimeout(10, TimeUnit.SECONDS)
    .callTimeout(10, TimeUnit.SECONDS)
    .build(),
) {
  fun fetchControlPlane(source: String): KiBotFetchResult {
    val cleanBase = baseUrl.trim().trimEnd('/')
    if (cleanBase.isEmpty()) {
      throw IOException("Base URL belum dikonfigurasi. Silakan atur di menu Pengaturan.")
    }
    val url = if (cleanBase.endsWith("/api/control-plane")) cleanBase else "$cleanBase/api/control-plane"
    Log.i(TAG, "fetch start source=$source url=$url")
    val requestBuilder = Request.Builder()
      .url(url)
      .header("Cache-Control", "no-cache")
      .header("Accept", "application/json")

    if (authUsername.isNotBlank() || authPassword.isNotBlank()) {
      val credentials = okhttp3.Credentials.basic(authUsername.trim(), authPassword)
      requestBuilder.header("Authorization", credentials)
    }

    val request = requestBuilder.build()

    client.newCall(request).execute().use { response ->
      val body = response.body?.string().orEmpty()
      Log.i(TAG, "fetch result source=$source http=${response.code} bytes=${body.length}")
      if (!response.isSuccessful) {
        throw IOException("HTTP ${response.code}: ${body.take(240)}")
      }
      val parsed = ControlPlaneParser.parse(
        rawJson = body,
        httpStatus = response.code,
        fetchedAtEpochMs = System.currentTimeMillis(),
        source = source,
      )
      return KiBotFetchResult(rawJson = body, httpStatus = response.code, parsed = parsed)
    }
  }

  companion object {
    private const val TAG = "KiBotApi"
  }
}
