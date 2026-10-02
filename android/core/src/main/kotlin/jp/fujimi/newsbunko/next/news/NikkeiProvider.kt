package jp.fujimi.newsbunko.next.news

import org.json.JSONObject

object NikkeiProvider : NewsProvider {
    override val name="日本経済新聞"
    override val processingSteps=listOf("kana", "translation", "media")
    private val domains=listOf("nikkei.com")
    private val pattern=Regex("/article/[A-Z0-9]+/?")
    fun htmlLinks(html:String,base:String)=NewsPrimitives.listing(NewsPrimitives.document(html,base),base,domains,pattern,"[data-paywall=true],[data-testid*=paywall],[class*=premium],[class*=Premium],img[alt*=会員限定]",setOf("会員限定","有料会員","有料記事"))
    override fun collect(homepage:String,transport:NewsTransport,checkpoint:()->Unit):List<String> {
        val page=NewsPrimitives.request(homepage,transport,checkpoint)
        if(!NewsPrimitives.hostMatches(NewsPrimitives.uri(page.finalUrl).host.orEmpty(),domains)) throw NewsValidationException("日经来源列表归属不匹配。")
        return NewsPrimitives.requireLinks(htmlLinks(page.html,page.finalUrl),name)
    }
    fun extractPage(html:String,url:String):NewsArticle {
        NewsPrimitives.validUrl(url,domains,pattern);val doc=NewsPrimitives.document(html,url);val records=NewsPrimitives.metadata(doc);NewsPrimitives.rejectPaid(records)
        val props=try { JSONObject(doc.selectFirst("script#js-k2-hydrate-client-exposed-context")?.data().orEmpty()).optJSONObject("paywallProps") ?: JSONObject() } catch (_:Exception) { JSONObject() }
        val lock=props.optJSONObject("lockStatus") ?: JSONObject()
        if(listOf(lock.opt("isLocked"),lock.opt("isDynamicLocked"),props.opt("isLockedArticle"),props.opt("isPaidUserOnlyArticle")).any { it==true }) throw NewsValidationException("日经当前文章为会员限定，未收录。")
        val unlocked=props.optString("kijiId")==NewsPrimitives.uri(url).path.trimEnd('/').substringAfterLast('/') && lock.optString("type")=="anonymous" && lock.opt("isLocked")==false && lock.opt("isDynamicLocked")==false && props.opt("isLockedArticle")==false && props.opt("isPaidUserOnlyArticle")==false
        val gate=doc.selectFirst("main#main-content,main") ?: doc
        NewsPrimitives.rejectGate(gate,"[data-testid=paywall],[data-paywall=true]")
        if(gate.selectFirst("[class*=mainPaywall]")!=null && !unlocked) throw NewsValidationException("日经本文存在会员阅读门槛，未收录。")
        val article=NewsPrimitives.scope(doc,"main#main-content article",name)
        val scope=article.selectFirst("[data-track-article-content]") ?: article;NewsPrimitives.clean(scope)
        scope.select("[class*=mainPaywall],figure[data-optimizely-selector]").remove()
        val body=NewsPrimitives.paragraphs(scope,"p[class*=paragraph_],h2,h3,div.container_c1tzahnc")
        return NewsArticle(url,NewsPrimitives.title(doc,records,"main#main-content article h1"),name,body.texts,NewsPrimitives.published(doc,records),NewsPrimitives.images(scope,"figure img",body,url).ifEmpty { NewsPrimitives.preview(doc,url) }+NewsPrimitives.videos(scope,url),listOf(url),paragraphHtml=body.html)
    }
    override fun fetchArticle(url:String,transport:NewsTransport,checkpoint:()->Unit):NewsArticle {
        NewsPrimitives.validUrl(url,domains,pattern);val page=NewsPrimitives.request(url,transport,checkpoint);NewsPrimitives.sameArticle(url,page.finalUrl,domains,pattern)
        return extractPage(page.html,page.finalUrl)
    }
}
