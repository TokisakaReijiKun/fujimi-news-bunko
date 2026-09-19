/* Reader navigation derives from EPUB nav/NCX, independent of spine file count. */
function bookBlockSupportsBookmark(_chapter, block) {
  return !['image', 'spacer'].includes(block.kind);
}

function setupBookNavigation(payload, root) {
  const panel = root.querySelector('.book-toc');
  const header = panel.querySelector(':scope > div');
  const official = payload.book.toc || [];
  const entries = official.length ? official : payload.book.chapters.map(ch => ({title:ch.title, chapter_id:ch.id, depth:0, anchor:''}));
  panel.replaceChildren(header);
  const front = payload.book.chapters[0];
  const navigation = entries.some(e => e.chapter_id === front?.id) ? entries : [{title:front.title,chapter_id:front.id,depth:0,anchor:''}, ...entries];
  for (const entry of navigation) {
    const button = document.createElement('button');
    button.type='button';button.dataset.chapterId=entry.chapter_id;button.dataset.anchor=entry.anchor || '';
    button.dataset.depth=Math.min(8,entry.depth || 0);button.style.setProperty('--toc-depth',String(Math.min(8,entry.depth || 0)));
    button.className=Number(entry.chapter_id)===Number(payload.chapter.id)?'active':'';
    button.textContent=entry.title;
    if(button.classList.contains('active'))button.setAttribute('aria-current','location');
    panel.append(button);
  }
  // Expose official TOC names in the picker rather than repeated XHTML titles.
  const selector=root.querySelector('.book-chapter-select');
  selector.replaceChildren(...payload.book.chapters.map(ch=>new Option(ch.title,ch.id,false,ch.id===payload.chapter.id)));
  root.style.removeProperty('--book-font-size');
  root.style.removeProperty('--book-line-height');
  if(payload.book.warnings?.length){
    const note=document.createElement('p');note.className='book-storage-note';note.textContent=payload.book.warnings.join(' ');root.querySelector('.book-reader-header').append(note);
  }
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { bookBlockSupportsBookmark };
}
