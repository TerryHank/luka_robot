/* Reparent existing controls once: preserve listeners, input values and polling. */
(() => {
  const by = id => document.getElementById(id);
  if (by('nxConsole')) return;
  const header = document.querySelector('body > header'), main = document.querySelector('body > main');
  if (!header || !main || !by('nxPeople')) return;
  const top = document.createElement('div'); top.id = 'nxConsole';
  top.innerHTML = '<div class="nc-top"><div class="nc-brand">LUKA <small>开发控制台</small></div><div class="nc-actions"></div><a href="/user">客户页面 ↗</a></div><nav class="nc-tabs" aria-label="测试工作区"></nav><div class="nc-status"></div><div class="nc-content"></div>';
  document.body.prepend(top);
  const views = {}, tabs = top.querySelector('nav'), content = top.querySelector('.nc-content');
  for (const [key, title] of [['navigation','地图导航'],['people','人体识别'],['patrol','巡航寻物'],['voice','语音音频'],['system','系统诊断']]) {
    const button = document.createElement('button'); button.type='button'; button.textContent=title; button.dataset.page=key;
    const view = document.createElement('div'); view.className='nc-view'; view.id='nc-'+key; button.setAttribute('aria-controls',view.id);
    tabs.append(button); content.append(view); views[key]=view;
    button.onclick=()=>select(key,true);
  }
  const move = (node, target) => { if(node) target.append(node); };
  const section = id => by(id)?.closest('section');
  const panel = id => by(id)?.closest('.panel');
  const services=section('nxStartAll'), voiceTest=by('nxVoiceTest')?.parentElement, wake=by('nxVoiceWake')?.parentElement, navInfo=by('nxNavStop')?.parentElement;
  for(const id of ['nxStartAll','nxRestartAll','nxNavStop']) move(by(id),top.querySelector('.nc-actions'));
  for(const id of ['status','nxNavStatus']) move(by(id),top.querySelector('.nc-status'));
  move(services,views.system); move(voiceTest,views.voice); move(wake,views.voice);
  move(navInfo,views.navigation); move(header,views.navigation); move(main,views.navigation);
  move(section('nxPosePick'),main.querySelector('aside'));
  move(by('nxPeople'),views.people);
  move(by('nxNavPatrolTest'),views.patrol);
  move(section('nxPatrolStart'),views.patrol); move(by('patrolRouteEditor'),views.patrol);
  move(by('musicPanel'),views.voice); move(by('voiceprintPanel'),views.voice);
  move(panel('llmInput'),views.voice); move(panel('healthChecks'),views.system); move(by('sonarMonitor'),views.system);
  const fold=(node,label,open=false)=>{if(!node)return;const d=document.createElement('details'),s=document.createElement('summary');s.textContent=label;d.open=open;node.before(d);d.append(s,node);};
  fold(panel('followStart'),'旧版跟随（未开放）');
  fold(panel('wpName'),'新增航点');
  fold(panel('x'),'详细位姿');
  const people=by('nxPeople');
  fold(people.querySelector('.np-note'),'安装与使用说明');
  fold(by('nxPeopleProfiles')?.closest('.np-card'),'已登记身份');
  fold(people.querySelector('.np-target-details'),'目标诊断详情');
  document.body.prepend(top); document.body.classList.add('nc-ready');
  function select(key,save){
    if(!views[key])key='navigation';
    for(const [k,v] of Object.entries(views)) v.hidden=k!==key;
    for(const b of tabs.children){b.setAttribute('aria-pressed',String(b.dataset.page===key));}
    if(save) history.replaceState(null,'','#'+(key==='people'?'nxPeople':'nc-'+key));
    requestAnimationFrame(()=>{window.dispatchEvent(new Event('resize'));if(key==='navigation')by('fit')?.click();});
  }
  function fromHash(){return location.hash==='#nxPeople'?'people':location.hash.replace('#nc-','');}
  window.addEventListener('hashchange',()=>select(fromHash(),false));
  window.scrollTo(0,0);
  setTimeout(()=>window.scrollTo(0,0),150);
  select(fromHash(),false);
})();
