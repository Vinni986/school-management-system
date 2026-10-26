document.addEventListener('DOMContentLoaded', function(){
  document.querySelectorAll('.progress b').forEach(function(el){ el.style.transition='width .8s ease'; });
  document.querySelectorAll('button').forEach(function(btn){
    if(btn.textContent.trim()==='') return;
    btn.addEventListener('click', function(){
      if(this.classList.contains('secondary-btn')) return;
      const old=this.innerHTML; this.innerHTML='<i class="fa-solid fa-check"></i> Ready'; setTimeout(()=>this.innerHTML=old,900);
    });
  });
});
