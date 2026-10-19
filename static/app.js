function toggleTheme(){
  var el=document.documentElement;
  var next=el.getAttribute('data-theme')==='dark'?'light':'dark';
  el.setAttribute('data-theme',next);
  try{localStorage.setItem('theme',next);}catch(e){}
}
(function(){
  try{var t=localStorage.getItem('theme');if(t)document.documentElement.setAttribute('data-theme',t);}catch(e){}
})();
function swapImg(el){
  var m=document.getElementById('pmain');
  if(!m)return;
  m.src=el.src;
  document.querySelectorAll('.galth').forEach(function(g){g.classList.remove('sel');});
  el.classList.add('sel');
}