"""Primitive postprocessing operations; publisher modules own the sequence."""
from pathlib import Path
import tempfile
import html
from urllib.parse import urlparse
from article_media import cache_media


class ArticleServices:
    def __init__(self, store, *, translate, ruby, now, stage, reset_budget, check, download,
                 translation_enabled, cancelled_error):
        self.store=store
        self.translator=translate
        self.ruby=ruby
        self.now=now
        self.stage=stage
        self.reset_budget=reset_budget
        self.check=check
        self.download=download
        self.translation_enabled=translation_enabled
        self.cancelled_error=cancelled_error

    def prepare(self, article, extracted, source_key):
        self.reset_budget();self.check()
        previous=dict(zip(article.get('paragraphs',[]),article.get('translated_paragraphs',[])))
        text=extracted['paragraphs'];translations=[previous.get(p,'') for p in text]
        result=dict(article)
        result.update(title=extracted['title'],url=extracted['url'],paragraphs=text,
                      published_at=extracted.get('published_at') or article['published_at'],
                      original_text='\n\n'.join(text),translated_paragraphs=translations,
                      full_translation='\n\n'.join(translations) if all(translations) else '',
                      failure_reason='',source_key=source_key,publisher_name=extracted.get('publisher_name',''),
                      status='ready',extraction_version=3,extracted_at=self.now())
        result['paragraph_kinds']=extracted.get('paragraph_kinds',[])
        result['paragraph_formats']=extracted.get('paragraph_formats',[])
        result['paragraph_links']=extracted.get('paragraph_links',[])
        return result

    def annotate(self, article):
        self.check()
        annotated=[]
        formats=article.get('paragraph_formats',[])
        for i, text in enumerate(article['paragraphs']):
            spans=formats[i] if i < len(formats) else []
            parts, cursor=[],0
            for start,end in spans:
                if not (isinstance(start,int) and isinstance(end,int) and cursor <= start < end <= len(text)):
                    raise ValueError('正文加粗区间与段落不匹配。')
                parts.extend((self.ruby(text[cursor:start]),'<strong>'+self.ruby(text[start:end])+'</strong>'))
                cursor=end
            parts.append(self.ruby(text[cursor:]))
            markup=''.join(parts)
            links=article.get('paragraph_links',[])
            links=links[i] if i<len(links) else []
            if links:
                cursor=0
                for link in links:
                    start,end=link['start'],link['end'];parsed=urlparse(link['url'])
                    if not (isinstance(start,int) and isinstance(end,int) and cursor<=start<end<=len(text)
                            and parsed.scheme in ('http','https') and parsed.hostname and not parsed.username and not parsed.password):
                        raise ValueError('正文链接区间或地址无效。')
                    cursor=end
                boundaries=sorted({0,len(text),*(v for span in spans for v in span),
                                   *(v for link in links for v in (link['start'],link['end']))})
                parts=[]
                for start,end in zip(boundaries,boundaries[1:]):
                    part=self.ruby(text[start:end])
                    if any(a<=start and end<=b for a,b in spans):part='<strong>'+part+'</strong>'
                    link=next((l for l in links if l['start']<=start and end<=l['end']),None)
                    if link:part='<a href="'+html.escape(link['url'],quote=True)+'" target="_blank" rel="noopener noreferrer">'+part+'</a>'
                    parts.append(part)
                markup=''.join(parts)
            if (article.get('paragraph_kinds',[]) or [])[i:i+1] == ['box']:
                lines=markup.split('\n')
                markup=''.join('<span class="article-box-'+('heading' if n==0 else 'line')+'">'+line+'</span>'
                               for n,line in enumerate(lines) if line.strip())
            elif (article.get('paragraph_kinds',[]) or [])[i:i+1] == ['box-plain']:
                markup=markup.replace('\n','<br>')
            annotated.append(markup)
        article['furigana_paragraphs']=annotated

    def translate(self, article, *, seconds, force=False):
        values=list(article.get('translated_paragraphs',[]))
        missing=[i for i in range(len(article['paragraphs']))
                 if not article['paragraphs'][i].strip().startswith('◇')
                 and (force or i>=len(values) or not values[i])]
        for i, paragraph in enumerate(article['paragraphs']):
            if paragraph.strip().startswith('◇'):
                values.extend(['']*(i + 1 - len(values)))
                values[i] = paragraph
        if not missing or not self.translation_enabled(): return
        values.extend(['']*(len(article['paragraphs'])-len(values)))
        self.stage('enhancing',f"{article['source_name']}：翻译正文（{len(missing)} 段）",seconds)
        try:
            translated=self.translator([article['paragraphs'][i] for i in missing])
            if not isinstance(translated,list) or len(translated)!=len(missing) or not all(isinstance(v,str) and v.strip() for v in translated):
                raise ValueError('翻译段落数量或内容不完整。')
            for i,value in zip(missing,translated): values[i]=value
            article.update(translated_paragraphs=values,full_translation='\n\n'.join(values) if all(values) else '')
        except self.cancelled_error: raise
        except Exception as error: article['failure_reason']='翻译未完成：'+str(error)
        finally: self.reset_budget()
        self.check()

    def save(self, article):
        self.reset_budget();self.check()
        saved=self.store.save(article)
        article.clear();article.update(saved)
        return article

    def media(self, article, extracted, *, seconds, download=None):
        self.reset_budget();self.check()
        self.stage('media',f"{article['source_name']}：保存图片和视频",seconds)
        count=0;total=len(extracted.get('images',[]))+len(extracted.get('videos',[]))
        def fetch(url):
            nonlocal count
            self.check();count+=1
            self.stage('media',f"{article['source_name']}：保存媒体 {count}/{total}",None)
            return (download or self.download)(url,max_bytes=32*1024*1024)
        try:
            with tempfile.TemporaryDirectory(dir=self.store.data/'diagnostics/transactions') as temporary:
                cached=cache_media(extracted,Path(temporary),fetch,check=self.check,cancelled_error=self.cancelled_error)
                self.reset_budget();self.check()
                return self.store.attach_cached(article['id'],cached,Path(temporary))
        finally: self.reset_budget()
