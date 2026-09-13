"""Primitive postprocessing operations; publisher modules own the sequence."""
from pathlib import Path
import tempfile
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
        return result

    def annotate(self, article):
        self.check()
        article['furigana_paragraphs']=[self.ruby(p) for p in article['paragraphs']]

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

    def media(self, article, extracted, *, seconds):
        self.reset_budget();self.check()
        self.stage('media',f"{article['source_name']}：保存图片和视频",seconds)
        count=0;total=len(extracted.get('images',[]))+len(extracted.get('videos',[]))
        def fetch(url):
            nonlocal count
            self.check();count+=1
            self.stage('media',f"{article['source_name']}：保存媒体 {count}/{total}",None)
            return self.download(url,max_bytes=32*1024*1024)
        try:
            with tempfile.TemporaryDirectory(dir=self.store.data/'diagnostics/transactions') as temporary:
                cached=cache_media(extracted,Path(temporary),fetch)
                self.reset_budget();self.check()
                return self.store.attach_cached(article['id'],cached,Path(temporary))
        finally: self.reset_budget()
