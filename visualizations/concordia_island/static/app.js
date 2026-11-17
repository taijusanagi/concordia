const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const escape = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pretty = (value) => String(value ?? '').replace(/_unit_(\d+)/g, ' · $1').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
const flat = (text) => String(text ?? '').replace(/\*\*/g, '').replace(/\s+/g, ' ').trim();
const short = (text, length = 120) => { const s = flat(text); return s.length > length ? s.slice(0, length - 1) + '…' : s; };
const state = {run:null,index:0,selected:null,tab:'mind',stage:'think',labels:true,timer:null,filter:'',positions:{},anchors:{}};
const SVG = 'http://www.w3.org/2000/svg';
const icons = {observe:'01',think:'02',act:'03',resolve:'04'};
const current = () => state.run?.events[state.index];
const person = (name = state.selected) => state.run?.agents.find(agent => agent.name === name);

function avatar(agent, index = 0) {
  const color = agent?.color || '#8d9762';
  const skin = ['#d9ad85','#bb8560','#e5bc98','#cd9976'][index % 4];
  const hair = ['#534538','#3b3b33','#6d5140','#44372c'][index % 4];
  return `<svg viewBox="0 0 28 32" aria-hidden="true"><path fill="${color}" d="M6 32V23H10V21H19V23H23V32Z"/><path fill="${skin}" d="M11 17H18V24H11Z"/><path fill="${skin}" d="M8 6H21V18H18V21H11V18H8Z"/><path fill="${hair}" d="M7 5H10V2H19V4H22V12H19V8H11V10H7Z"/><path fill="#443f35" d="M11 12H13V14H11ZM17 12H19V14H17Z"/><path fill="#aa7960" d="M13 17H17V18H13Z"/><path fill="#fff9e6" d="M11 23L14.5 27L18 23L16.5 32H12.5Z"/></svg>`;
}

function notice(message, error = false) {
  const element = $('#notice');
  element.textContent = message; element.hidden = !message;
  element.classList.toggle('error', error);
}

async function getJSON(url) {
  const response = await fetch(url);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `Unable to load (${response.status}).`);
  return payload;
}

async function loadRuns(preferred) {
  $('#refreshButton').disabled = true;
  try {
    const {runs} = await getJSON('/api/runs');
    $('#runSelect').innerHTML = runs.map(run => `<option value="${escape(run.id)}">${escape(run.id)}</option>`).join('');
    if (!runs.length) {
      stop(); state.run = null; $('#workspace').hidden = true; $('#runStats').innerHTML = '';
      $('#runSelect').innerHTML = '<option>No saved runs</option>';
      notice('No replayable runs found. Finish an Island simulation with --output_dir=./local_runs/<run_name>, then click refresh. A replay requires raw_log.json.');
      return;
    }
    const chosen = runs.some(run => run.id === preferred) ? preferred : runs[0].id;
    $('#runSelect').value = chosen;
    await loadRun(chosen);
  } catch (error) { notice(error.message, true); }
  finally { $('#refreshButton').disabled = false; }
}

async function loadRun(id) {
  stop(); notice('Opening your recorded world…'); $('#workspace').hidden = true;
  try {
    const run = await getJSON('/api/runs/' + encodeURIComponent(id));
    if (!run.events.length) throw new Error('This run has no resident action records to replay. Choose another completed Island run.');
    state.run = run; state.index = 0; state.selected = run.events[0].agent;
    state.filter = ''; state.tab = 'mind'; state.stage = 'think'; state.positions = {};
    $('#eventFilter').innerHTML = '<option value="">All residents</option>' + run.agents.map(agent => `<option value="${escape(agent.name)}">${escape(agent.name)}</option>`).join('');
    $('#agentCount').textContent = run.agents.length;
    $('#runStats').innerHTML = [
      [run.agents.length, 'RESIDENTS'],
      [run.state.ticks ?? run.clocks.length, 'TICKS'],
      [run.events.length, 'RECORDED ACTIONS'],
    ].map(([value,label]) => `<div class="stat"><strong>${escape(value)}</strong><span>${label}</span></div>`).join('');
    $('#worldTitle').textContent = run.atlas.meta?.display_name || 'Concordia Island';
    $('#eventSlider').max = run.events.length - 1;
    $('#workspace').hidden = false; notice('');
    drawWorld(); render();
    history.replaceState(null, '', '?run=' + encodeURIComponent(id));
  } catch (error) { state.run = null; notice(error.message, true); }
}

function eventForSelected() {
  const event = current();
  if (!event || event.agent === state.selected) return event;
  const previous = state.run.events.slice(0, state.index + 1).filter(e => e.agent === state.selected);
  // Never present a future resident's action as if it had already happened.
  return previous.at(-1) || null;
}

function locationsFor(event = current()) {
  // Map positions come only from location_history.json. Agent log selection
  // within one tick must not change the displayed world state.
  return event?.snapshot_locations || {};
}

function renderResidents() {
  const locations = locationsFor();
  $('#residentList').innerHTML = state.run.agents.map((agent,index) => `<button class="resident-card ${agent.name === state.selected ? 'active' : ''}" data-agent="${escape(agent.name)}" aria-pressed="${agent.name === state.selected}"><span class="avatar" style="background:${agent.color}18">${avatar(agent,index)}</span><span><span class="resident-name">${escape(agent.name)}</span><span class="resident-role" style="display:block">${escape(agent.work ? pretty(agent.work) : 'Island resident')}</span><span class="resident-location" style="display:block">⌖ ${escape(pretty(locations[agent.name] || 'Not recorded'))}</span></span></button>`).join('');
}

function renderEvents() {
  const events = state.run.events.filter(event => !state.filter || event.agent === state.filter);
  $('#eventList').innerHTML = events.map(event => `<button class="event-row ${event.id === state.index ? 'active' : ''}" data-event="${event.id}" aria-current="${event.id === state.index ? 'step' : 'false'}"><span class="event-number">${String(event.id + 1).padStart(2,'0')}</span><span class="event-body"><span class="event-meta"><span class="tiny-dot" style="background:${person(event.agent).color}"></span>${escape(event.agent)}<span> TICK ${escape(event.tick || '—')}</span></span><span class="event-excerpt" style="display:block">${escape(short(event.resolution.replace(/^Event Resolution:\s*\[event\]\s*/,'') || event.action, 180))}</span></span><span class="event-arrow">↗</span></button>`).join('');
  const active = $('.event-row.active');
  if (active) {
    // Follow the current action inside the list without scrolling the page.
    const list = $('#eventList');
    const bounds = list.getBoundingClientRect();
    const row = active.getBoundingClientRect();
    if (row.top < bounds.top) list.scrollTop -= bounds.top - row.top;
    else if (row.bottom > bounds.bottom) list.scrollTop += row.bottom - bounds.bottom;
  }
}

function rawDetails(data, label = 'Recorded prompt & output') {
  return `<details class="record-details"><summary>${label}</summary><pre>${escape(typeof data === 'string' ? data : JSON.stringify(data,null,2))}</pre></details>`;
}

function renderInspector() {
  const agent = person(); if (!agent) return;
  const index = state.run.agents.indexOf(agent);
  $('#selectedResident').innerHTML = `<span class="avatar" style="background:${agent.color}18">${avatar(agent,index)}</span><div><h2>${escape(agent.name)}</h2><p>${escape([agent.profile.age ? `${agent.profile.age} years old` : '', pretty(agent.work || 'Island resident')].filter(Boolean).join(' · '))}</p></div>`;
  $$('.inspector-tabs button').forEach(button => {
    const selected = button.dataset.tab === state.tab;
    button.classList.toggle('active', selected); button.setAttribute('aria-selected', selected);
  });
  if (state.tab === 'profile') { renderProfile(agent); return; }
  if (state.tab === 'memories') { renderMemories(agent); return; }
  const event = eventForSelected();
  if (!event) {
    $('#inspectorContent').innerHTML = `<p class="section-kicker">WAITING FOR THEIR TURN</p><h3>A story about to begin.</h3><p class="body-copy">${escape(agent.name)} has no action recorded before the selected event. Step forward, or open their persona.</p>`;
    return;
  }
  const earlier = event.id !== state.index ? ' · LATEST EARLIER RECORD' : '';
  let content = `<div class="event-tag"><span>EVENT ${String(event.id + 1).padStart(2,'0')} / TICK ${event.tick || '—'}</span><span>${earlier ? 'EARLIER RECORD' : 'RECORDED OUTPUT'}</span></div><p class="soft-note" style="margin:0 0 12px">Action context: ${escape(event.clock || 'Time not recorded')}. The map shows the saved tick snapshot separately.</p><div class="stage-nav" aria-label="Decision stage">${Object.keys(icons).map(stage => `<button data-stage="${stage}" class="${state.stage === stage ? 'active' : ''}" aria-pressed="${state.stage === stage}"><span>${icons[stage]}</span>${stage[0].toUpperCase()+stage.slice(1)}</button>`).join('')}</div>`;
  if (state.stage === 'think') {
    content += '<p class="section-kicker">THE ESA DECISION PIPELINE</p><h3>What’s on their mind?</h3><p class="soft-note" style="margin:0 0 16px">Recorded component outputs. Expand a card to read the full text and its saved transcript.</p>';
    content += event.thoughts.map((thought,index) => `<details class="thought-item" ${index === 0 || thought.id === 'EmotionalExperience' ? 'open' : ''}><summary><span class="thought-number">${String(index+1).padStart(2,'0')}</span>${escape(thought.label)}${thought.cached ? '<span class="cache-tag">CACHED</span>' : ''}</summary><div class="thought-text"><p class="body-copy">${escape(thought.text || 'No text recorded.')}</p>${rawDetails(thought.record)}</div></details>`).join('');
    if (!event.thoughts.length) content += '<p class="body-copy">No component outputs were saved for this event.</p>';
  } else if (state.stage === 'observe') {
    content += `<p class="section-kicker">THEIR VIEW OF THE WORLD</p><h3>What did they notice?</h3><div class="callout"><p class="body-copy">${escape(event.observation || 'No observation was recorded for this event.')}</p></div><p class="soft-note">This is the observation supplied to the agent. In async runs, it may describe an earlier event.</p>`;
  } else if (state.stage === 'act') {
    content += `<p class="section-kicker">THE AGENT’S PROPOSAL</p><h3>From thought to action.</h3><p class="body-copy">${escape(event.action || 'No action was recorded.')}</p><p class="soft-note">A proposed action is not yet a confirmed world outcome.</p>`;
  } else {
    content += `<p class="section-kicker">THE GAME MASTER’S RESPONSE</p><h3>How was it resolved?</h3><p class="body-copy">${escape(event.resolution || 'No resolution was recorded.')}</p><div class="profile-section" style="margin-top:22px"><h4>RECORDED GM LOCATION CONTEXT</h4>${Object.entries(event.context_locations).map(([name,loc])=>`<div class="state-row"><span>${escape(name)}</span><span>${escape(pretty(loc))}</span></div>`).join('')}</div>${rawDetails(event.gm_record, 'Full recorded Game Master context')}<p class="soft-note">This is the recorded narrative and resolution context, which may contain older positions. The map uses only the separate saved location-history snapshot for this tick.</p>`;
  }
  $('#inspectorContent').innerHTML = content;
}

function renderProfile(agent) {
  const p = agent.profile;
  if (!Object.keys(p).length) {
    $('#inspectorContent').innerHTML = '<p class="section-kicker">INITIAL BACKGROUND</p><h3>A life before the story.</h3><p class="soft-note">No matching generated persona file was found. These are initial background entries from the saved memory bank.</p>' + agent.initial_memories.map(memory=>`<p class="body-copy">${escape(memory)}</p>`).join('');
    return;
  }
  let html = '<p class="section-kicker">GENERATED STARTING PERSONA</p><h3>A life before the story.</h3>';
  html += `<p>${[p.economic_class,p.relationship_status,...(p.hobbies||[])].filter(Boolean).map(tag=>`<span class="pill">${escape(pretty(tag))}</span>`).join('')}</p>`;
  for (const [key,label] of [['personality','PERSONALITY'],['original_backstory','BACKGROUND'],['home_place','HOME'],['work_place','WORKPLACE']]) {
    if(p[key]) html += `<div class="profile-section"><h4>${label}</h4><p class="body-copy">${escape(key.endsWith('place') ? pretty(p[key]) : p[key])}</p></div>`;
  }
  if(p.traits && typeof p.traits === 'object') {
    html += '<div class="profile-section"><h4>STARTING TRAITS</h4>';
    for(const [key,value] of Object.entries(p.traits)) {
      const max = ['openness','conscientiousness','extraversion','agreeableness','neuroticism'].includes(key) ? 5 : 1;
      const width = Math.min(100, Math.max(0, Number(value) / max * 100));
      html += `<div class="trait"><span>${escape(pretty(key))}</span><span class="trait-track"><i style="width:${width}%"></i></span><span class="trait-value">${Number(value).toFixed(1)}</span></div>`;
    }
    html += '<p class="soft-note">Big Five shown on a 1–5 scale; other traits on a 0–1 scale. Values come from the generated persona.</p></div>';
  }
  if(p.formative_memories?.length) html += '<div class="profile-section"><h4>FORMATIVE MEMORIES</h4>'+p.formative_memories.map(memory=>`<p class="body-copy">${escape(memory)}</p>`).join('')+'</div>';
  html += '<p class="soft-note">Persona files are matched by name from local populations. They are starting data, not a record of changes during this run.</p>';
  $('#inspectorContent').innerHTML = html;
}

function renderMemories(agent) {
  $('#inspectorContent').innerHTML = `<p class="section-kicker">FINAL SAVED MEMORY BANK</p><h3>The things they carry.</h3><p class="soft-note" style="margin:0">${agent.memories.length} entries at the end of the run. This view does not rewind with the replay.</p><input id="memorySearch" class="memory-search" type="search" placeholder="Search their memories…" aria-label="Search resident memories"><div id="memoryResults"></div>`;
  filterMemories('');
}

function filterMemories(query) {
  const list = person().memories.map((memory,index)=>({memory,index})).filter(({memory})=>String(memory).toLowerCase().includes(query.toLowerCase()));
  $('#memoryResults').innerHTML = list.length ? list.map(({memory,index})=>`<div class="memory-item"><span class="memory-index">${String(index+1).padStart(2,'0')}</span>${escape(typeof memory === 'string' ? memory : JSON.stringify(memory))}</div>`).join('') : '<p class="body-copy">No memories match your search.</p>';
}

function canonical(id) {
  let value = String(id || '').replace(/_unit_\d+$/, '').replace(/_common_room$/, '');
  const atlas = state.run.atlas;
  return atlas.sim_ids?.[value] || atlas.aliases?.[value] || value;
}

function drawTree(x,y,size=1) {
  return `<g transform="translate(${x} ${y}) scale(${size})"><ellipse cy="13" rx="12" ry="5" fill="#8da274" opacity=".18"/><path d="M-2 0H2V13H-2Z" fill="#a69270"/><path d="M0-23L-12-3H-7L-16 6H16L7-3H12Z" fill="#89a375"/><path d="M0-23V6H16L7-3H12Z" fill="#6e8e61"/></g>`;
}

function building(x,y,index,id) {
  const home = /apts|commons|ridge|estates|creek|apartments|village|heights|point/.test(id);
  const clinic = /clinic|hospital/.test(id);
  const civic = /center|school|library/.test(id);
  const w = home ? 34 : 39, h = home ? 34 : 27;
  const roof = clinic ? '#b7bbb0' : civic ? '#9aa48d' : ['#c68c6b','#a9ad95','#bba686'][index%3];
  const wall = home ? '#f3e4c4' : '#eee6cd';
  const rows = home ? 2 : 1;
  let windows = '';
  for(let row=0;row<rows;row++) for(let col=0;col<3;col++) windows += `<path d="M${-w+7+col*9} ${-h+11+row*11}v6l5 2v-6z" fill="#9cafa0"/><path d="M${7+col*9} ${-h+19+row*11}v6l5-2v-6z" fill="#8b9e91"/>`;
  return `<g class="map-location" transform="translate(${x} ${y})" tabindex="0" role="button" aria-label="Inspect residents at ${escape(pretty(id))}" data-place="${escape(id)}"><title>${escape(pretty(id))}</title><ellipse cy="15" rx="${w+15}" ry="17" fill="#83976b" opacity=".13"/><path d="M${-w}-15L0 0L${w}-15V${-h-15}L0 ${-h}L${-w} ${-h-15}Z" fill="${wall}"/><path d="M0 0L${w}-15V${-h-15}L0 ${-h}Z" fill="#d4cfb5"/>${windows}<path d="M-7-3V-17L0-14V0Z" fill="#a69578"/><path class="building-roof" d="M${-w-5} ${-h-16}L-3 ${-h-38}L${w+6} ${-h-24}L${w} ${-h-14}L0 ${-h+1}Z" fill="${roof}"/><path d="M-3 ${-h-38}L0 ${-h+1}L${-w-5} ${-h-16}Z" fill="#ffffff" opacity=".16"/>${clinic ? '<path d="M9-35h6v6h6v6h-6v6H9v-6H3v-6h6Z" fill="#f8f5e9"/>' : ''}</g>`;
}

function drawWorld() {
  const important = new Set();
  state.run.agents.forEach(agent=>{if(agent.home)important.add(canonical(agent.home));if(agent.work)important.add(canonical(agent.work));});
  state.run.events.forEach(event=>{
    Object.values(event.context_locations).forEach(loc=>{if(loc)important.add(canonical(loc));});
    Object.values(event.snapshot_locations).forEach(loc=>{if(loc)important.add(canonical(loc));});
  });
  ['town_square','park','library'].forEach(id=>important.add(id));
  const ids = [...important];
  const slots = [[215,245],[740,238],[785,447],[460,247],[555,438],[235,457],[495,340],[170,345],[755,340],[360,510],[640,530],[360,165],[630,160],[880,310],[100,420],[460,550]];
  const atlasPlaces = new Map((state.run.atlas.places||[]).map(place=>[place.id,place]));
  state.anchors = {};
  ids.forEach((id,index)=>{
    // Schematic layout: no inferred route or geographic precision.
    const slot = slots[index] || [110 + (index % 7)*125, 150 + Math.floor(index/7)*105];
    state.anchors[id] = {x:slot[0],y:slot[1],name:atlasPlaces.get(id)?.name || pretty(id)};
  });
  let svg = `<defs><pattern id="fieldGrid" width="32" height="32" patternUnits="userSpaceOnUse" patternTransform="rotate(30)"><path d="M32 0H0V32" fill="none" stroke="#dce5d0" stroke-width=".6"/></pattern><filter id="softShadow" x="-50%" y="-50%" width="200%" height="200%"><feDropShadow dx="0" dy="2" stdDeviation="3" flood-color="#516744" flood-opacity=".12"/></filter></defs><rect width="1000" height="650" fill="#e7eddf"/><rect width="1000" height="650" fill="url(#fieldGrid)"/><path d="M930-30C850 95 1030 170 944 290S879 410 970 510L1060 690H1100V-30Z" fill="#c0d8d1"/><path d="M921-30C840 94 1020 170 934 290S869 410 960 510L1050 690" fill="none" stroke="#d3e1cb" stroke-width="18"/><path d="M40 320C190 335 280 315 380 335S570 360 690 330S820 285 930 300" fill="none" stroke="#d5ddc7" stroke-width="35"/><path d="M40 320C190 335 280 315 380 335S570 360 690 330S820 285 930 300" fill="none" stroke="#f6f4e5" stroke-width="25"/><path d="M40 320C190 335 280 315 380 335S570 360 690 330S820 285 930 300" fill="none" stroke="#dedecb" stroke-width="1" stroke-dasharray="7 8"/><path d="M310 50Q340 200 385 335T430 650M710 35Q650 200 690 330T650 650" fill="none" stroke="#d5ddc7" stroke-width="23"/><path d="M310 50Q340 200 385 335T430 650M710 35Q650 200 690 330T650 650" fill="none" stroke="#f6f4e5" stroke-width="16"/><ellipse cx="505" cy="343" rx="65" ry="37" fill="#d6dfc6"/><ellipse cx="505" cy="343" rx="37" ry="22" fill="#f2efd8"/><ellipse cx="505" cy="343" rx="15" ry="9" fill="#c1d4c5"/><path d="M505 324v20" stroke="#a5b79a" stroke-width="3"/><text class="building-label" x="435" y="106">N E I G H B O R H O O D</text><text class="building-label" x="80" y="590">B R E C K S V I L L E · F I E L D S T U D Y</text>`;
  for(let i=0;i<65;i++) {
    const x = 35+(i*139)%880, y=75+(i*83)%490;
    const close = Object.values(state.anchors).some(p=>Math.abs(p.x-x)<65 && Math.abs(p.y-y)<65);
    if(!close && Math.abs(y-330)>36)svg += drawTree(x,y,.7+(i%4)*.15);
  }
  svg = svg.replace('B R E C K S V I L L E · F I E L D S T U D Y', escape((state.run.atlas.meta?.display_name || 'Island').toUpperCase()) + ' · FIELD STUDY');
  svg += '<g id="placeLayer">';
  Object.entries(state.anchors).sort((a,b)=>a[1].y-b[1].y).forEach(([id,p],index)=>{
    if(id==='park') svg+=`<g transform="translate(${p.x} ${p.y})"><ellipse rx="48" ry="28" fill="#cfdcbd"/>${drawTree(-15,-4)}${drawTree(19,5,.8)}<path d="M-12 16L17 25" stroke="#b7c79e" stroke-width="5"/></g>`;
    else if(id!=='town_square')svg+=building(p.x,p.y,index,id);
    svg += `<text class="map-label" data-label="place" x="${p.x}" y="${p.y+35}" text-anchor="middle">${escape(short(p.name,27))}</text>`;
  });
  svg += '</g><g id="routeLayer"></g><g id="agentLayer">';
  state.run.agents.forEach((agent,index)=>{
    svg+=`<g class="map-agent" id="mapAgent${index}" tabindex="0" role="button" aria-label="Follow ${escape(agent.name)}" data-agent="${escape(agent.name)}"><title>${escape(agent.name)}</title><ellipse cy="8" rx="13" ry="6" fill="#526344" opacity=".17"/><ellipse class="agent-ring" cy="6" rx="19" ry="10" stroke="${agent.color}"/><g transform="translate(-11 -24) scale(.8)">${avatar(agent,index).replace('<svg viewBox="0 0 28 32" aria-hidden="true">','').replace('</svg>','')}</g><text class="agent-name-label" y="28" text-anchor="middle">${escape(agent.name.split(' ')[0])}</text><g class="thought-bubble" transform="translate(8 -40)"><rect x="-2" y="-7" width="27" height="18" rx="6" fill="#fffef8" stroke="#d2ddc4"/><path d="M2 10L0 15L9 10" fill="#fffef8"/><text x="5" y="6" font-size="13" fill="#91a17f">···</text></g></g>`;
  });
  svg+='</g><text id="unmappedNotice" class="map-unmapped" x="22" y="90"></text>';
  $('#worldMap').innerHTML=svg;
}

function renderMap() {
  const locations=locationsFor(), occupied={};let routes='',unmapped=0;
  state.run.agents.forEach((agent,index)=>{
    const location=locations[agent.name];
    const anchor=state.anchors[canonical(location)];
    const element=$(`#mapAgent${index}`);
    if(!anchor){element.style.display='none';unmapped++;return;}
    element.style.display='';
    const key=canonical(location);const offset=occupied[key]||0;occupied[key]=offset+1;
    const x=anchor.x-32+offset*29,y=anchor.y+24;
    const previous=state.positions[agent.name];
    if(previous && (previous.x!==x || previous.y!==y))routes+=`<path class="map-route" d="M${previous.x} ${previous.y}Q${(previous.x+x)/2} ${Math.min(previous.y,y)-35} ${x} ${y}" stroke="${agent.color}"><title>Illustrative transition between recorded positions</title></path>`;
    state.positions[agent.name]={x,y};
    element.setAttribute('transform',`translate(${x} ${y})`);
    element.classList.toggle('selected',agent.name===state.selected);
    element.querySelector('.thought-bubble').style.display=agent.name===state.selected?'':'none';
  });
  $('#routeLayer').innerHTML=routes;
  $('#unmappedNotice').textContent=unmapped?`${unmapped} resident location${unmapped>1?'s':''} not recorded in this view`:'';
  $$('[data-label="place"]').forEach(label=>label.style.display=state.labels?'':'none');
  $('#mapCaption').textContent=Object.keys(locations).length ? `Tick ${current().tick || '—'} · recorded location snapshot` : 'No location snapshot recorded for this tick';
  $('#locationStatus').textContent=`${state.run.agents.length-unmapped} / ${state.run.agents.length} LOCATED`;
}

function render() {
  if(!state.run)return;
  const event=current();
  $('#worldTime').textContent=`Tick ${event.tick || '—'} · saved positions`;
  $('#tickLabel').textContent=`TICK ${event.tick || '—'} / ${state.run.state.ticks ?? state.run.clocks.length}`;
  $('#eventPosition').textContent=`EVENT ${state.index+1} OF ${state.run.events.length}`;
  $('#eventSlider').value=state.index;
  $('#previousButton').disabled=state.index===0;
  $('#nextButton').disabled=state.index===state.run.events.length-1;
  renderResidents();renderEvents();renderInspector();renderMap();
}

function setIndex(index, follow=true) {
  if(!state.run)return;
  state.index=Math.max(0,Math.min(state.run.events.length-1,Number(index)));
  if(follow)state.selected=current().agent;
  render();
}

function stop() {
  clearInterval(state.timer);state.timer=null;
  $('#playButton').textContent='▶';$('#playButton').setAttribute('aria-label','Play replay');
}

function play() {
  if(!state.run)return;
  if(state.timer){stop();return;}
  if(state.index===state.run.events.length-1)setIndex(0);
  $('#playButton').textContent='Ⅱ';$('#playButton').setAttribute('aria-label','Pause replay');
  state.timer=setInterval(()=>{
    if(state.index>=state.run.events.length-1){stop();return;}
    setIndex(state.index+1);
  },Number($('#speedSelect').value));
}

$('#runSelect').addEventListener('change',event=>loadRun(event.target.value));
$('#refreshButton').addEventListener('click',()=>loadRuns($('#runSelect').value));
$('#previousButton').addEventListener('click',()=>{stop();setIndex(state.index-1);});
$('#nextButton').addEventListener('click',()=>{stop();setIndex(state.index+1);});
$('#playButton').addEventListener('click',play);
$('#speedSelect').addEventListener('change',()=>{if(state.timer){stop();play();}});
$('#eventSlider').addEventListener('input',event=>{stop();setIndex(event.target.value);});
$('#eventFilter').addEventListener('change',event=>{state.filter=event.target.value;renderEvents();});
$('#labelsButton').addEventListener('click',()=>{state.labels=!state.labels;$('#labelsButton').setAttribute('aria-pressed',state.labels);renderMap();});
document.addEventListener('click',event=>{
  const agent=event.target.closest('[data-agent]');
  if(agent){state.selected=agent.dataset.agent;renderResidents();renderInspector();renderMap();}
  const row=event.target.closest('[data-event]');
  if(row){stop();setIndex(row.dataset.event);}
  const stage=event.target.closest('[data-stage]');
  if(stage){state.stage=stage.dataset.stage;renderInspector();}
  const tab=event.target.closest('[data-tab]');
  if(tab){state.tab=tab.dataset.tab;renderInspector();}
  const place=event.target.closest('[data-place]');
  if(place){const agent=state.run.agents.find(agent=>canonical(locationsFor()[agent.name])===place.dataset.place);if(agent){state.selected=agent.name;render();}}
});
document.addEventListener('input',event=>{if(event.target.id==='memorySearch')filterMemories(event.target.value);});
document.addEventListener('keydown',event=>{
  if(event.target.matches('input,select,textarea')||$('#aboutDialog').open)return;
  if((event.key==='Enter'||event.key===' ')&&event.target.matches('.map-agent,.map-location')){event.preventDefault();event.target.dispatchEvent(new MouseEvent('click',{bubbles:true}));return;}
  if(event.key==='ArrowRight'){event.preventDefault();stop();setIndex(state.index+1);}
  if(event.key==='ArrowLeft'){event.preventDefault();stop();setIndex(state.index-1);}
  if(event.code==='Space'&&!event.target.matches('button')){event.preventDefault();play();}
});
$('#aboutButton').addEventListener('click',()=>$('#aboutDialog').showModal());
$('#closeAbout').addEventListener('click',()=>$('#aboutDialog').close());
$('#gotItButton').addEventListener('click',()=>$('#aboutDialog').close());
await loadRuns(new URLSearchParams(location.search).get('run'));
