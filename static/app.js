function toggleTheme(){
  var el=document.documentElement;
  var next=el.getAttribute('data-theme')==='dark'?'light':'dark';
  el.setAttribute('data-theme',next);
  try{localStorage.setItem('theme',next);}catch(e){}
}
(function(){
  try{var t=localStorage.getItem('theme');if(t)document.documentElement.setAttribute('data-theme',t);}catch(e){}
})();
(function(){
  var btn=document.querySelector('.mobile-menu');
  var links=document.querySelector('.links');
  var actions=document.querySelector('.user-actions');
  if(!btn||!links||!actions)return;
  btn.addEventListener('click',function(){
    var open=btn.getAttribute('aria-expanded')==='true';
    btn.setAttribute('aria-expanded',!open);
    links.classList.toggle('open');
    actions.classList.toggle('open');
  });
  // Close menu when clicking a link
  document.querySelectorAll('.links a, .user-actions a').forEach(function(a){
    a.addEventListener('click',function(){
      btn.setAttribute('aria-expanded','false');
      links.classList.remove('open');
      actions.classList.remove('open');
    });
  });
})();
function swapImg(el){
  var m=document.getElementById('pmain');
  if(!m)return;
  m.src=el.src;
  document.querySelectorAll('.galth').forEach(function(g){g.classList.remove('sel');});
  el.classList.add('sel');
}