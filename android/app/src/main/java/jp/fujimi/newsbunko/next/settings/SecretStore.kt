package jp.fujimi.newsbunko.next.settings

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class SecretStore(context: Context) {
    private val preferences = context.getSharedPreferences("protected-secrets", Context.MODE_PRIVATE)
    private val alias = "fujimi-next-settings"

    @Synchronized
    fun saveDeepSeekKey(value: String): Boolean {
        if (value.length !in 8..512 || value.any { it.isWhitespace() || it.isISOControl() }) return false
        return try {
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.ENCRYPT_MODE, key())
            cipher.updateAAD("deepseek".toByteArray(Charsets.UTF_8))
            val encrypted = cipher.doFinal(value.toByteArray(Charsets.UTF_8))
            preferences.edit().putString("deepseek-iv", Base64.encodeToString(cipher.iv, Base64.NO_WRAP))
                .putString("deepseek-value", Base64.encodeToString(encrypted, Base64.NO_WRAP)).commit()
        } catch (_: Exception) { false }
    }

    @Synchronized
    fun readDeepSeekKey(): String? {
        val iv = preferences.getString("deepseek-iv", null) ?: return null
        val encrypted = preferences.getString("deepseek-value", null) ?: return null
        return try {
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, Base64.decode(iv, Base64.NO_WRAP)))
            cipher.updateAAD("deepseek".toByteArray(Charsets.UTF_8))
            String(cipher.doFinal(Base64.decode(encrypted, Base64.NO_WRAP)), Charsets.UTF_8)
        } catch (_: Exception) { null }
    }

    fun isConfigured(): Boolean = readDeepSeekKey() != null
    @Synchronized fun clearDeepSeekKey(): Boolean = preferences.edit().remove("deepseek-iv").remove("deepseek-value").commit()

    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(alias, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256).build())
        }.generateKey()
    }
}
