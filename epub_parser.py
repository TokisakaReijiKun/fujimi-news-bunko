"""EPUB spine, official navigation and safe reading blocks (no publisher scripts)."""
from datetime import datetime, timezone, timedelta
import hashlib
import io
import posixpath
import re
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET
import zipfile

from bs4 import BeautifulSoup, NavigableString, Tag

CST = timezone(timedelta(hours=8))


def resolve(base, href):
    p = urlsplit(href)
    if p.scheme or p.netloc or '\\' in href:
        raise ValueError('EPUB 资源必须使用包内相对路径。')
    path = posixpath.normpath(posixpath.join(posixpath.dirname(base), unquote(p.path))) if p.path else base
    if path.startswith(('../', '/')) or ':' in path:
        raise ValueError('EPUB 包含不安全资源路径。')
    return path, unquote(p.fragment)


def anchor_id(path, anchor=''):
    return 'epub-' + hashlib.sha256((path+'#'+anchor).encode()).hexdigest()[:20]


def normalized_text(node):
    clone = BeautifulSoup(str(node),'html.parser')
    for tag in clone.select('rt, rp'): tag.decompose()
    for br in clone.find_all('br'): br.replace_with('\n')
    # XML formatting whitespace around ruby is not part of the sentence.
    return re.sub(r'[\t\r\n]+[ ]*', '', clone.get_text()).strip(' \t\r\n')


STYLE = {
    'text-align':r'(?:left|right|center|justify|start|end)',
    'font-weight':r'(?:normal|bold|[1-9]00)', 'font-style':r'(?:normal|italic|oblique)',
    'font-size':r'(?:[5-9]\d|1\d\d|200)%|(?:0\.[5-9]|1(?:\.\d)?|2)em',
    'text-indent':r'-?\d(?:\.\d+)?(?:em|rem)',
    'text-decoration':r'(?:underline|line-through|none)',
    'text-combine-upright':r'all|none', 'text-emphasis-style':r'(?:filled|open)?\s*(?:dot|sesame|circle)',
    'vertical-align':r'(?:super|sub|baseline)',
}


def safe_style(value):
    result = []
    for part in value.split(';'):
        key,sep,val = part.partition(':');key=key.strip().lower();val=val.strip().lower()
        if sep and key in STYLE and re.fullmatch(STYLE[key],val): result.append(key+':'+val)
    return ';'.join(result)


def css_rules(css):
    # Preserve only simple text formatting, never execute arbitrary global CSS.
    out=[]
    css=re.sub(r'/\*.*?\*/','',css,flags=re.S)
    for selectors,body in re.findall(r'([^{}]+)\{([^{}]*)\}',css):
        style=safe_style(body)
        if not style: continue
        for selector in selectors.split(','):
            selector=selector.strip()
            if re.fullmatch(r'(?:[a-zA-Z][\w-]*)?(?:[.#][\w-]+)?',selector):out.append((selector,style))
    return out


def sanitize(node, path, assets, *, normalized=False):
    soup=BeautifulSoup(str(node),'html.parser')
    for bad in soup.select('script,style,iframe,object,embed,form,input,button,link,meta,foreignObject'):
        bad.decompose()
    # Most EPUB covers use an SVG wrapper around a raster image.
    for svg in list(soup.find_all('svg')):
        replacements=[]
        for image in svg.find_all('image'):
            href=image.get('xlink:href') or image.get('href','')
            try: resource,_=resolve(path,href)
            except ValueError:continue
            if resource in assets:
                img=soup.new_tag('img');img['data-book-asset']=resource;img['alt']=image.get('aria-label','');replacements.append(img)
        for replacement in replacements:svg.insert_before(replacement)
        svg.decompose()
    allowed={'p','div','span','ruby','rt','rp','rb','em','strong','b','i','u','s','br','img','a','h1','h2','h3','h4','h5','h6',
             'blockquote','ul','ol','li','figure','figcaption','table','tbody','thead','tr','td','th','sup','sub','hr','pre','code'}
    for el in list(soup.find_all(True)):
        if el.name not in allowed:el.unwrap();continue
        attrs={}
        if el.get('id'):
            identifier=el['id']
            attrs['id']=identifier if normalized and re.fullmatch(r'epub-[0-9a-f]{20}',identifier) else anchor_id(path,identifier)
        if el.get('lang'):attrs['lang']=el['lang'][:20]
        style=safe_style(el.get('style',''))
        classes=el.get('class',[])
        if 'tcy' in classes:style+=';text-combine-upright:all'
        for alignment in ('left','right','center'):
            if 'align-'+alignment in classes:style+=';text-align:'+alignment
        size=next((re.fullmatch(r'font-(\d{3})per',c) for c in classes if re.fullmatch(r'font-(\d{3})per',c)),None)
        if size:style+=';font-size:'+str(int(size.group(1)))+'%'
        style=safe_style(style)
        if style:attrs['style']=style
        if el.name=='img':
            resource=el.get('data-book-asset')
            if not resource:
                try:resource,_=resolve(path,el.get('src',''))
                except ValueError:resource=None
            if resource not in assets:el.decompose();continue
            attrs.update({'data-book-asset':resource,'alt':el.get('alt','')})
            for dimension in ('width','height'):
                if str(el.get(dimension,'')).isdigit():attrs[dimension]=el[dimension]
        if el.name=='a':
            href=el.get('href','')
            if href.startswith(('https://','http://')):attrs.update(href=href,rel='noreferrer noopener',target='_blank')
            elif href:
                try:
                    destination,fragment=resolve(path,href)
                    attrs['data-book-href']=destination+'#'+anchor_id(destination,fragment)
                except ValueError:pass
            elif normalized and el.get('data-book-href'):
                try:
                    destination,fragment=resolve('',el['data-book-href'])
                    if re.fullmatch(r'epub-[0-9a-f]{20}',fragment):
                        attrs['data-book-href']=destination+'#'+fragment
                except ValueError:pass
        el.attrs=attrs
    # Drop indentation added by XML pretty printers while retaining inline spaces.
    for text in list(soup.find_all(string=True)):
        if '\n' in text or '\r' in text:
            text.replace_with(re.sub(r'[\t\r\n]+[ ]*','',str(text)))
    return str(soup)


def parse_epub(blob, filename):
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        infos=z.infolist()
        if len(infos)>12000 or sum(i.file_size for i in infos)>200*1024*1024:
            raise ValueError('EPUB 解压后过大（上限 200 MB / 12000 文件）。')
        names=set()
        for info in infos:
            n=info.filename
            if n.startswith(('/','\\')) or '..' in n.replace('\\','/').split('/') or ':' in n or n in names:
                raise ValueError('EPUB 包含不安全或重复路径。')
            names.add(n)
        if 'META-INF/encryption.xml' in names:
            encryption=ET.fromstring(z.read('META-INF/encryption.xml'))
            algorithms=[e.get('Algorithm','') for e in encryption.iter() if e.tag.endswith('EncryptionMethod')]
            if any(a not in ('http://www.idpf.org/2008/embedding','http://ns.adobe.com/pdf/enc#RC') for a in algorithms):
                raise ValueError('此 EPUB 包含加密内容，不能导入。')
        container=ET.fromstring(z.read('META-INF/container.xml'))
        opf=next(e.get('full-path') for e in container.iter() if e.tag.endswith('rootfile'))
        if opf not in names:raise ValueError('找不到 EPUB package。')
        package=ET.fromstring(z.read(opf));metadata=next(e for e in package if e.tag.endswith('metadata'))
        value=lambda tag:next((''.join(e.itertext()).strip() for e in metadata if e.tag.endswith('}'+tag)), '')
        manifest={e.attrib['id']:dict(e.attrib) for e in package.iter() if e.tag.endswith('}item')}
        for item in manifest.values():item['path']=resolve(opf,item['href'])[0]
        spine=next(e for e in package if e.tag.endswith('spine'))
        spine_items=[manifest[e.attrib['idref']] for e in spine if e.attrib.get('idref') in manifest and e.attrib.get('linear')!='no']
        assets={}
        for item in manifest.values():
            path=item['path']
            if path not in names:continue
            if item.get('media-type','').startswith('image/') and not path.lower().endswith('.svg'):
                assets[path]=z.read(path)
        cover_id=next((e.get('content') for e in metadata if e.get('name')=='cover'),None)
        cover=next((e['path'] for k,e in manifest.items() if ('cover-image' in e.get('properties','').split() or k==cover_id) and e['path'] in assets),'')
        toc=[]
        nav=next((e for e in manifest.values() if 'nav' in e.get('properties','').split()),None)
        if nav and nav['path'] in names:
            soup=BeautifulSoup(z.read(nav['path']),'html.parser')
            navnode=next((n for n in soup.find_all('nav') if 'toc' in n.get('epub:type','').split() or n.get('role')=='doc-toc'),None)
            if navnode:
                for link in navnode.select('li > a[href]'):
                    path,fragment=resolve(nav['path'],link['href'])
                    depth=max(0,len(list(link.parents))-len(list(navnode.parents))-3)//2
                    depth=sum(1 for p in link.parents if getattr(p,'name','')=='li')-1
                    toc.append({'title':link.get_text(' ',strip=True),'path':path,'fragment':fragment,'depth':depth})
        if not toc:
            ncx=manifest.get(spine.get('toc')) or next((e for e in manifest.values() if e.get('media-type')=='application/x-dtbncx+xml'),None)
            if ncx and ncx['path'] in names:
                tree=ET.fromstring(z.read(ncx['path']))
                def walk(parent,depth=0):
                    for point in parent:
                        if point.tag.split('}')[-1]!='navPoint':continue
                        label=next((e for e in point if e.tag.endswith('navLabel')),None)
                        content=next((e for e in point if e.tag.endswith('content')),None)
                        if content is not None:
                            path,fragment=resolve(ncx['path'],content.get('src',''))
                            toc.append({'title':''.join(label.itertext()).strip() if label is not None else '', 'path':path,'fragment':fragment,'depth':depth})
                        walk(point,depth+1)
                navmap=next((e for e in tree.iter() if e.tag.endswith('navMap')),None)
                if navmap is not None:walk(navmap)
        raw_blocks=[]; source_spans={};warnings=[]
        for item in spine_items:
            if 'html' not in item.get('media-type',''):continue
            path=item['path']
            if path not in names:raise ValueError('EPUB 缺少正文文件：'+path)
            soup=BeautifulSoup(z.read(path),'html.parser');body=soup.body or soup
            rules=[]
            for link in soup.select('link[rel="stylesheet"][href]'):
                csspath,_=resolve(path,link['href'])
                if csspath in names:rules.extend(css_rules(z.read(csspath).decode('utf-8',errors='replace')))
            for selector,style in rules:
                for element in body.select(selector):element['style']=style+';'+element.get('style','')
            for bad in body.select('script,style,iframe,object,form'):bad.decompose()
            containers={'body','div','section','main','article'}
            atoms={'p','h1','h2','h3','h4','h5','h6','blockquote','ul','ol','figure','table','pre','hr','svg','img'}
            pieces=[]
            def walk(node):
                if isinstance(node,NavigableString):
                    if node.strip():
                        tag=soup.new_tag('p');tag.string=str(node);pieces.append(tag)
                    return
                if not isinstance(node,Tag):return
                if node.name in atoms:
                    pieces.append(node);return
                if node.get('id'):
                    tag=soup.new_tag('span');tag['id']=node['id'];pieces.append(tag)
                for child in list(node.children):walk(child)
            walk(body)
            start=len(raw_blocks);pending=None
            for index,node in enumerate(pieces):
                inherited=''
                for ancestor in reversed(list(node.parents)):
                    for alignment in ('left','right','center'):
                        if 'align-'+alignment in getattr(ancestor,'attrs',{}).get('class',[]):inherited='text-align:'+alignment+';'
                if inherited:node['style']=inherited+node.get('style','')
                markup=sanitize(node,path,assets);text=normalized_text(node)
                img='data-book-asset=' in markup
                if node.name=='svg' and img:text=''
                if not text and not img and not node.get('id') and not node.find(['br','hr']):continue
                kind='image' if img and not text else 'heading' if node.name in ('h1','h2','h3','h4','h5','h6') else 'spacer' if not text else 'paragraph'
                identifiers=[node.get('id')] + [e.get('id') for e in node.select('[id]')]
                marked=bool(re.search(r'opacity\s*:\s*0?\.4\b',node.get('style','')))
                block={'kind':kind,'html':markup,'text_ja':text,'text_zh':'','furigana_html':'',
                       'source_href':path,'source_block_index':index,'anchor_ids':[anchor_id(path,a) for a in identifiers if a],
                       'id':len(raw_blocks)+1,'original_language':'ja','bilingual_pair':False}
                # This converter explicitly marks the Japanese half with opacity .4.
                # Pair only adjacent, marked paragraphs; never infer from kanji alone.
                if marked and pending is not None and raw_blocks and raw_blocks[-1] is pending and not pending.get('marked') and pending['text_ja'] and kind in ('paragraph','heading'):
                    chinese=raw_blocks.pop()
                    block.update(text_zh=chinese['text_ja'],bilingual_pair=True,source_translation_html=chinese['html'])
                    block['anchor_ids']+=chinese['anchor_ids']
                block['marked']=marked
                if not raw_blocks or len(raw_blocks)==start:block['anchor_ids'].insert(0,anchor_id(path))
                raw_blocks.append(block);pending=block if kind in ('paragraph','heading') else None
            source_spans[path]=(start,len(raw_blocks))
            if not cover:
                first=next((b for b in raw_blocks[start:] if b['kind']=='image'),None)
                if first:
                    m=re.search(r'data-book-asset="([^"]+)"',first['html']);cover=m.group(1) if m else ''
        if not raw_blocks:raise ValueError('没有找到可阅读的章节。')
        for entry in toc:
            span=source_spans.get(entry['path'])
            if not span:entry['offset']=None;warnings.append('目录目标不存在：'+entry['title']);continue
            offset=span[0]
            if entry['fragment']:
                target=anchor_id(entry['path'],entry['fragment'])
                offset=next((i for i in range(*span) if target in raw_blocks[i]['anchor_ids']),None)
                if offset is None:warnings.append('目录锚点不存在：'+entry['title'])
            entry['offset']=offset
        valid=[e for e in toc if e.get('offset') is not None]
        boundaries={e['offset']:e for e in reversed(valid) if e['depth']==0}
        if not valid:
            for path,(start,end) in source_spans.items():
                if end<=start:continue
                block=raw_blocks[start]
                label=block['text_ja'][:55] if block['kind']=='heading' else ('表紙・挿絵' if block['kind']=='image' else '本文')
                boundaries[start]={'title':label,'path':path,'fragment':'','depth':0,'offset':start}
            valid=list(boundaries.values())
        if 0 not in boundaries:boundaries[0]={'title':'Chapter1','depth':0,'offset':0,'is_frontmatter':True}
        starts=sorted(boundaries);chapters=[]
        for number,start in enumerate(starts,1):
            end=starts[number] if number<len(starts) else len(raw_blocks)
            blocks=raw_blocks[start:end]
            if not blocks:continue
            for i,b in enumerate(blocks):b.update(id=i+1,block_index=i);b.pop('marked',None)
            paths=list(dict.fromkeys(b['source_href'] for b in blocks))
            chapters.append({'id':number,'title':boundaries[start]['title'],'source_href':paths[0], 'source_hrefs':paths,
                             'nav_depth':0,'blocks':blocks,'block_count':len(blocks),'voice_mode':'browser','audio':None,
                             'global_start':start,'is_frontmatter':boundaries[start].get('is_frontmatter',False),
                             'show_heading':blocks[0]['kind'] not in ('heading','image')})
        entries=[]
        for e in valid:
            ch=next(c for c in reversed(chapters) if c['global_start']<=e['offset'])
            anchor=anchor_id(e['path'],e['fragment'])
            entries.append({'id':len(entries)+1,'title':e['title'],'depth':e['depth'],'chapter_id':ch['id'],
                            'block_index':e['offset']-ch['global_start'],'anchor':anchor,'source_href':e['path'],'source_fragment':e['fragment']})
        return {'title':value('title') or filename.rsplit('.',1)[0],'author':value('creator'),'language':value('language'),
                'original_filename':filename,
                'series':'','volume':'','chapters':chapters,'toc':entries,'bookmarks':[],'progress':{},'parser_version':2,
                'imported_at':datetime.now(CST).isoformat(),'last_read_at':'','cover_path':cover,
                'block_count':len(raw_blocks),'warnings':warnings,'original_available':True,
                'writing_mode':'vertical' if spine.get('page-progression-direction')=='rtl' else 'horizontal'},assets
