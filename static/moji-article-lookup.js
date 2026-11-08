/* MOJi阅读 APK assets/h5hybrid/assets/MOJiArticleDetail-121467f1.js.
 * st/ne/j/lt/at/se/le below are the original function bodies, without changes.
 * mount only binds their content element, audio state and native bridge to this app.
 */
(() => {
  'use strict';
  window.MojiArticleLookup = {
    mount(root, clickWord, playing) {
      const MOJiArticleContentId = root.id;
      const Api = { clickWord: 'clickContent' };
      let isPlayingAudio = false;
      let target = null;
      const m = (action, text) => clickWord(text, target.closest('ruby, .moji-toolkit-org'));
      root.addEventListener('click', event => { target = event.target; isPlayingAudio = playing(); }, true);
      function st(){const e=document.getElementById(MOJiArticleContentId);e.onclick=ne}
      function ne(e){const t=le();if(lt(e.target)===!0||at(e.target)&&isPlayingAudio&&!t(e.target,se("--active")))return;let n=e.target,i="",o=n;(n.parentNode.nodeName.match(/RUBY|RB|RT/)||n.parentNode.className.includes("moji-toolkit-org"))&&(n=n.parentNode);try{switch(n.nodeName){case"RUBY":o=n.querySelector("rb"),i=o.textContent;break;case"RB":i=n.textContent;break;case"RT":o=n.parentNode.querySelector("rb"),i=o.textContent;break;case"SPAN":n.className.includes("moji-toolkit-org")&&(i=n.innerText);break;default:break}}catch(c){return}i&&(window.getSelection().removeAllRanges(),o.classList.add("on-click-word"),setTimeout(()=>{o.classList.remove("on-click-word")},500),m(Api.clickWord,i))}
      function j(e,t){const i=document.getElementById(MOJiArticleContentId).querySelectorAll(e);for(let o=0,c=i.length;o<c;o++)if(i[o].contains(t))return!0}
      function lt(e){return j("a",e)}
      function at(e){return j(".moji-article-srt",e)}
      function se(e){const t=e;return function(n){return n&&n.classList?n.classList.contains(t):!1}}
      function le(){const e=arguments.length>0&&arguments[0]!==void 0?arguments[0]:100;let t=0;function n(i,o){if(t++,t>=e)return!1;const c=i.parentNode;if(c)return o(c)?c:n(c,o)}return n}
      st();
    }
  };
})();
