package jp.fujimi.newsbunko.next.dictionary

import com.atilika.kuromoji.ipadic.Tokenizer

/** MOJi APK t8.a.b: default IPADIC tokenizer, querying the surface, not the base form. */
object MojiLookupTokenizer {
    private val tokenizer by lazy { Tokenizer() }

    @Synchronized fun surfaces(text: String): List<String> = tokenizer.tokenize(text).map { it.surface }
}
