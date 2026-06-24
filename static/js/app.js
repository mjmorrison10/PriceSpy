
// ════════════════════════════ FIREBASE ════════════════════════════
var firebaseConfig = {
  apiKey: "AIzaSyBkI43lN_TiTtc9XL1QrEaFJh_s4n6Nhik",
  authDomain: "pricespy-12095.firebaseapp.com",
  projectId: "pricespy-12095",
  storageBucket: "pricespy-12095.firebasestorage.app",
  messagingSenderId: "726753231810",
  appId: "1:726753231810:web:d60b003525a06175800c5b",
  measurementId: "G-4DEM1DZ0CL"
};
var fbApp = null, fbAuth = null, fbDb = null;
try {
  fbApp = firebase.initializeApp(firebaseConfig);
  fbAuth = firebase.auth();
  fbDb = firebase.firestore();
} catch(e) {}

// ════════════════════════════ HELPERS ════════════════════════════
var D = function(id) { return document.getElementById(id); };
var HIDE = function(id) { D(id).style.display = 'none'; };
var SHOW = function(id) { D(id).style.display = 'flex'; };
var FMT = function(n) { return (n || 0).toFixed ? Number(n).toFixed(2) : '0.00'; };
var getToken = function() { return localStorage.getItem('ps-tk') || ''; };

var EL = function(tag, cls, parent) {
  var el = document.createElement(tag);
  if (cls) el.className = cls;
  if (parent) parent.appendChild(el);
  return el;
};
var TXT = function(el, text) { el.textContent = text || ''; return el; };

var chart = null;
var data = null;
var period = '6m';
var token = '';
var user = null;
var isReg = false;
var lotItems = [];
var PERIODS = ['1w','1m','3m','6m','1y','2y','3y','5y','10y'];

var CLAB = {
  all:'All Conditions', new:'🆕 New', new_other:'📦 New Other', new_defects:'⚠️ New w/ Defects',
  manufacturer_refurbished:'🔧 Mfr Refurbished', seller_refurbished:'🔧 Seller Refurbished',
  used:'👌 Used', very_good:'👍 Very Good', good:'✅ Good', acceptable:'⚠️ Acceptable', for_parts:'🔧 For Parts'
};
function CL(c) { return CLAB[c] || c || 'Unknown'; }

var MARKET_SEGMENT_HELP = {
  auto:'Auto market detection',
  strict:'Strict exact market',
  broad:'Broad market',
  phone_exact_storage:'Phones: Exact storage',
  phone_any_storage:'Phones: Any storage',
  phone_allow_damaged:'Phones: Allow damaged / as-is',
  shoe_adult:'Shoes: Adult only',
  shoe_youth:'Shoes: Youth / GS / Toddler',
  shoe_womens:'Shoes: Women\'s',
  card_raw:'Cards: Raw only',
  card_graded:'Cards: Graded only',
  tool_only:'Tools: Tool only',
  tool_kit:'Tools: Kit / battery included',
  book_standard:'Books: Standard copy',
  book_collectible:'Books: Collectible / special edition',
  console_standard:'Console: Standard model',
  console_special_edition:'Console: Special edition',
  console_console_only:'Console: Console / tablet only'
};

function segLabel(v) { return MARKET_SEGMENT_HELP[v] || MARKET_SEGMENT_HELP.auto; }

// Theme
if (localStorage.getItem('ps-thm') === 'light') {
  document.documentElement.setAttribute('data-theme','light');
  D('navTheme').textContent = '☀️';
}
D('navTheme').onclick = function() {
  var n = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', n);
  D('navTheme').textContent = n === 'light' ? '☀️' : '🌙';
  localStorage.setItem('ps-thm', n);
};

// Bible verses
var VRS = [
  {t:'"For I know well the plans I have in mind for you."',r:'Jeremiah 29:11'},
  {t:'"I can do all things through him who strengthens me."',r:'Philippians 4:13'},
  {t:'"The Lord is my shepherd; there is nothing I shall lack."',r:'Psalm 23:1'},
  {t:'"Be strong and courageous."',r:'Deuteronomy 31:6'},
  {t:'"Come to me, all you who labor and are burdened."',r:'Matthew 11:28'},
  {t:'"Rejoice in the Lord always."',r:'Philippians 4:4'},
  {t:'"For God so loved the world."',r:'John 3:16'},
  {t:'"Trust in the Lord with all your heart."',r:'Proverbs 3:5'},
  {t:'"The steadfast love of the Lord never ceases."',r:'Lamentations 3:22'},
  {t:'"Behold, I am with you always."',r:'Matthew 28:20'},
  {t:'"Let your light shine before men."',r:'Matthew 5:16'},
  {t:'"Blessed are the peacemakers."',r:'Matthew 5:9'},
  {t:'"The Lord bless you and keep you."',r:'Numbers 6:24-25'},
  {t:'"Do not be anxious about anything."',r:'Philippians 4:6'},
  {t:'"I am the way, the truth, and the life."',r:'John 14:6'},
  {t:'"Seek first the kingdom of God."',r:'Matthew 6:33'},
  {t:'"The Lord is my light and my salvation."',r:'Psalm 27:1'},
  {t:'"Be still and know that I am God."',r:'Psalm 46:11'},
  {t:'"This is the day that the Lord has made."',r:'Psalm 118:24'},
  {t:'"We know that all things work together for good."',r:'Romans 8:28'},
  {t:'"The Lord is near to the brokenhearted."',r:'Psalm 34:18'},
  {t:'"For where your treasure is, there your heart will be."',r:'Matthew 6:21'},
  {t:'"You shall love the Lord your God with all your heart."',r:'Matthew 22:37'},
  {t:'"Let nothing disturb you. All things pass. God never changes."',r:'St. Teresa'}
];
function setVerse() {
  var v = VRS[new Date().getHours() % VRS.length];
  D('vt').textContent = v.t;
  D('vr').textContent = '\u2014 ' + v.r;
}
setVerse();
setInterval(setVerse, 3600000);

// Auth
try {
  token = localStorage.getItem('ps-tk') || '';
  user = JSON.parse(localStorage.getItem('ps-usr') || 'null');
} catch(e) {}
if (user) { D('navAuth').textContent = user.display_name || 'User'; }
function openAccount() {
  if (token && user) {
    D('accountInfo').innerHTML = '<div style="font-size:1.2rem;font-weight:600;margin-bottom:4px">' + (user.display_name || 'User') + '</div><div style="color:var(--t2);font-size:.85rem">' + (user.email || '') + '</div>';
    SHOW('accountOv');
  } else { SHOW('authOv'); }
}
D('navAuth').onclick = openAccount;
D('userBtn').onclick = openAccount;
D('logoutBtn').onclick = function() {
  token = ''; user = null;
  localStorage.removeItem('ps-tk'); localStorage.removeItem('ps-usr');
  D('navAuth').textContent = '👤';
  HIDE('accountOv');
};
D('connectEbayBtn').onclick = async function() {
  if (!token) { alert('Login first to connect your eBay seller account.'); return; }
  try {
    var r = await fetch('/api/ebay/auth?token=' + getToken());
    var d = await r.json();
    if (!r.ok) throw new Error(d.error || 'Failed');
    if (d.auth_url) window.open(d.auth_url, '_blank');
  } catch(err) { alert('Could not start eBay auth: ' + err.message); }
};

D('googleLogin').onclick = async function() {
  if (!fbAuth) { D('aerr').textContent = 'Firebase not connected.'; D('aerr').classList.add('on'); return; }
  try {
    var provider = new firebase.auth.GoogleAuthProvider();
    var result = await fbAuth.signInWithPopup(provider);
    var idToken = await result.user.getIdToken();
    var r = await fetch('/api/auth/firebase', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({id_token: idToken})});
    var respData = await r.json();
    if (!r.ok) { D('aerr').textContent = respData.error || 'Server error.'; D('aerr').classList.add('on'); return; }
    token = respData.token; user = respData.user;
    localStorage.setItem('ps-tk', token); localStorage.setItem('ps-usr', JSON.stringify(user));
    HIDE('authOv'); D('navAuth').textContent = user.display_name || user.email;
  } catch(err) { D('aerr').textContent = err.message; D('aerr').classList.add('on'); }
};
D('atog').onclick = function() {
  isReg = !isReg;
  D('authT').textContent = isReg ? '📝 Create Account' : '👤 Login';
  D('asub').textContent = isReg ? 'Create' : 'Login';
  D('an').style.display = isReg ? 'block' : 'none';
  D('aerr').classList.remove('on');
};
D('asub').onclick = async function() {
  var e = D('ae').value.trim();
  var p = D('ap').value.trim();
  var n = D('an').value.trim();
  if (!e || !p) { D('aerr').textContent = 'Email and password required'; D('aerr').classList.add('on'); return; }
  try {
    var ep = isReg ? '/api/auth/register' : '/api/auth/login';
    var b = isReg ? {email:e, password:p, display_name:n || e.split('@')[0]} : {email:e, password:p};
    var r = await fetch(ep, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(b)});
    var respData = await r.json();
    if (!r.ok) throw new Error(respData.error || 'Failed');
    token = respData.token; user = respData.user;
    localStorage.setItem('ps-tk', token); localStorage.setItem('ps-usr', JSON.stringify(user));
    HIDE('authOv'); D('navAuth').textContent = user.display_name || 'User';
  } catch(err) { D('aerr').textContent = err.message; D('aerr').classList.add('on'); }
};

// Navigation
var PAGES = ['search','quick','watch','inventory','lot','deals','trending','bulk','dash','hot','roi','promoted','seller','title','analytics'];
function showPage(p) {
  for (var i = 0; i < PAGES.length; i++) {
    var pg = D('pg-' + PAGES[i]);
    if (pg) pg.classList.toggle('on', PAGES[i] === p);
  }
  var navBtns = document.querySelectorAll('[data-pg]');
  for (var i = 0; i < navBtns.length; i++) {
    navBtns[i].classList.toggle('ac', navBtns[i].dataset.pg === p);
  }
  if (p === 'watch') { loadWl(); loadSavedSearches(); }
  if (p === 'inventory') loadInv();
  if (p === 'deals') loadDh();
  if (p === 'trending') loadTr();
  if (p === 'dash') loadDash();
  if (p === 'hot') loadHot();
  if (p === 'bulk') D('bulkRes').innerHTML = '';
  if (p === 'promoted') D('poRes').innerHTML = '';
  if (p === 'seller') loadSellerDashboard();
  if (p === 'title') D('toRes').innerHTML = '';
  if (p === 'analytics') D('anRes').innerHTML = '';
}
var navEls = document.querySelectorAll('[data-pg]');
for (var i = 0; i < navEls.length; i++) {
  navEls[i].onclick = (function(pg) { return function() { showPage(pg); }; })(navEls[i].dataset.pg);
}

// Mobile bottom nav + more menu
var BOTTOM_PAGES = ['search','quick','inventory'];
var MORE_PAGES = PAGES.filter(function(p) { return BOTTOM_PAGES.indexOf(p) === -1; });
var PAGE_ICONS = {search:'🔍',quick:'⚡',watch:'⭐',inventory:'📦',lot:'🧮',deals:'📋',trending:'📊',bulk:'📥',dash:'📈',hot:'🔥',roi:'💵',promoted:'📢',seller:'🏪',title:'✍️',analytics:'📊'};
function populateMoreMenu() {
  var grid = D('moreGrid');
  grid.innerHTML = '';
  for (var i = 0; i < MORE_PAGES.length; i++) {
    var p = MORE_PAGES[i];
    var btn = EL('button', 'bt bt-g', grid);
    btn.innerHTML = '<span>' + PAGE_ICONS[p] + '</span><span>' + p.charAt(0).toUpperCase() + p.slice(1) + '</span>';
    btn.onclick = (function(pg) { return function() { HIDE('moreOv'); showPage(pg); }; })(p);
  }
}
populateMoreMenu();
D('moreBtn').onclick = function() { SHOW('moreOv'); };
D('moreOv').onclick = function(e) { if (e.target === D('moreOv')) HIDE('moreOv'); };

function updateNavActive(p) {
  var headerPills = document.querySelectorAll('header .pil[data-pg]');
  for (var i = 0; i < headerPills.length; i++) {
    headerPills[i].classList.toggle('ac', headerPills[i].dataset.pg === p);
  }
  var bottomBtns = document.querySelectorAll('.bottom-nav .bn-btn[data-pg]');
  for (var i = 0; i < bottomBtns.length; i++) {
    bottomBtns[i].classList.toggle('ac', bottomBtns[i].dataset.pg === p);
  }
}

var _origShowPage = showPage;
showPage = function(p) {
  _origShowPage(p);
  updateNavActive(p);
};

function setConds(avail, labels) {
  if (labels) { for (var k in labels) { CLAB[k] = labels[k]; } }
  var curr = D('cond').value;
  var sel = D('cond');
  sel.innerHTML = '';
  var std = ['all', 'new', 'new_other', 'new_defects', 'manufacturer_refurbished', 'seller_refurbished', 'used', 'very_good', 'good', 'acceptable', 'for_parts'];
  if (avail && avail.length) {
    for (var i = 0; i < avail.length; i++) {
      if (std.indexOf(avail[i]) === -1) std.push(avail[i]);
    }
  }
  for (var i = 0; i < std.length; i++) {
    var c = std[i];
    var o = document.createElement('option');
    o.value = c; o.textContent = c === 'all' ? 'All Conditions' : CL(c); sel.appendChild(o);
  }
  sel.value = curr;
}

// Search
function ld(o) { D('sp').classList.toggle('on', o); D('st').textContent = o ? 'Searching eBay...' : ''; }
function er(m) { D('em').textContent = m; D('em').classList.add('on'); }
function ce() { D('em').classList.remove('on'); }

// Clear All — reset search form, cached data, and results to a clean slate
function clearAll() {
  D('q').value = '';
  D('bp').value = '';
  D('ship').value = '';
  D('promo').value = '0';
  D('cond').value = 'all';
  D('storeTier').value = 'none';
  D('catSearch').value = '';
  D('catId').value = '';
  D('catSug').style.display = 'none';
  if (D('marketSeg')) D('marketSeg').value = 'auto';
  if (D('qdSeg')) D('qdSeg').value = 'auto';
  if (D('photoMarketSeg')) D('photoMarketSeg').value = 'auto';
  data = null;
  D('res').classList.remove('on');
  D('res').innerHTML = '';
  ce();
  // Reset shipping estimator extras
  if (D('shipWeight')) D('shipWeight').value = '';
  if (D('shipDims')) D('shipDims').value = '';
  _resetShipBadge('shipEstBadge');
  _resetShipBadge('qdsEstBadge');
  lastPhotoEstimate = null;
  // Un-highlight any active preset buttons
  var bpPresets = document.querySelectorAll('.bp-pre');
  for (var i=0; i<bpPresets.length; i++) { bpPresets[i].classList.remove('bt-p'); bpPresets[i].classList.add('bt-g'); }
  var shipPresets = document.querySelectorAll('.ship-pre');
  for (var i=0; i<shipPresets.length; i++) { shipPresets[i].classList.remove('bt-p'); shipPresets[i].classList.add('bt-g'); }
  D('q').focus();
}

async function search(filterCond) {
  var q = D('q').value.trim();
  if (!q) return;
  ld(true); ce(); D('res').classList.remove('on');
  
  // Show skeleton loader
  D('res').innerHTML = '<div class="cd"><div class="skeleton" style="height:40px;width:60%"></div><div class="gd"><div class="skeleton" style="height:80px"></div><div class="skeleton" style="height:80px"></div><div class="skeleton" style="height:80px"></div></div></div>';
  D('res').classList.add('on');

  var c = filterCond || D('cond').value || 'all';
  var bp = parseFloat(D('bp').value) || 0;
  var st = D('storeTier').value || 'none';
  var sh = parseFloat(D('ship').value) || 0;
  var pr = parseFloat(D('promo').value) || 0;
  var catId = D('catId').value || '';
  var seg = D('marketSeg') ? (D('marketSeg').value || 'auto') : 'auto';
  var u = '/api/search?q=' + encodeURIComponent(q) + '&period=' + period + '&condition=' + encodeURIComponent(c);
  if (bp > 0) u += '&buy_price=' + bp.toFixed(2);
  u += '&store_tier=' + st;
  if (sh > 0) u += '&shipping=' + sh.toFixed(2);
  if (pr > 0) u += '&promoted_rate=' + pr.toFixed(2);
  if (catId) u += '&ebay_category_id=' + encodeURIComponent(catId);
  if (seg && seg !== 'auto') u += '&market_segment=' + encodeURIComponent(seg);
  try {
    var r = await fetch(u);
    var respData = await r.json();
    if (!r.ok) throw new Error(respData.error || 'Search failed');
    data = respData;
    if (!data.sold_summary || !data.sold_summary.count) {
      // No sold results is OK — still show active and market note
    }
    setConds(data.available_conditions, data.condition_labels);
    renderAll(data);
    D('res').classList.add('on');
    D('res').scrollIntoView({behavior:'smooth', block:'start'});
  } catch(err) { er(err.message); }
  finally { ld(false); }
}

D('qb').onclick = function() { search(); };
D('q').onkeydown = function(e) { if (e.key === 'Enter') search(); };
D('cond').onchange = function() { if (data) { recalcFromExistingData(); } else { search(); } };
if (D('marketSeg')) D('marketSeg').onchange = function() { if (D('q').value.trim()) search(); };

// When only financial parameters change, recalculate from existing data (no eBay API call)
D('storeTier').onchange = function() { recalcFromExistingData(); };
D('promo').onchange = function() { recalcFromExistingData(); };
D('bp').onchange = function() { recalcFromExistingData(); };
// Flag that distinguishes "AI is filling the ship field" from "user typed it".
// estimateShipping() sets this to suppress the badge-clear on programmatic fills.
var _aiFillingShip = false;
D('ship').onchange = function() {
  if (!_aiFillingShip) _resetShipBadge('shipEstBadge');
  recalcFromExistingData();
};

async function recalcFromExistingData() {
  if (!data) { search(); return; }
  // Update data with current form values, then recalculate without eBay API
  data.buy_price = parseFloat(D('bp').value) || 0;
  data.shipping_cost = parseFloat(D('ship').value) || 0;
  data.store_tier = D('storeTier').value || 'none';
  data.promoted_rate = parseFloat(D('promo').value) || 0;
  data.active_filter_condition = D('cond').value || 'all';
  data.market_segment = D('marketSeg') ? (D('marketSeg').value || 'auto') : 'auto';
  try {
    ld(true);
    var r = await fetch('/api/recalculate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({data: data})
    });
    var d = await r.json();
    if (!r.ok) throw new Error(d.error || 'Recalculate failed');
    data = d;
    renderAll(data);
  } catch(e) {
    er(e.message || 'Could not recalculate');
  } finally {
    ld(false);
  }
}

function setBuyPreset(val, el) {
  D('bp').value = val;
  var btns = document.querySelectorAll('.bp-pre');
  for (var i=0; i<btns.length; i++) { btns[i].classList.remove('bt-p'); btns[i].classList.add('bt-g'); }
  if (el) { el.classList.remove('bt-g'); el.classList.add('bt-p'); }
  recalcFromExistingData();
}
function setShipPreset(val, el) {
  D('ship').value = val;
  var btns = document.querySelectorAll('.ship-pre');
  for (var i=0; i<btns.length; i++) { btns[i].classList.remove('bt-p'); btns[i].classList.add('bt-g'); }
  if (el) { el.classList.remove('bt-g'); el.classList.add('bt-p'); }
  recalcFromExistingData();
}

// ════════════════════════════ SHIPPING ESTIMATOR ════════════════════════════
// Gemini-powered shipping cost estimator (USPS / UPS ground).
// Caches the last AI estimate per item in JS to avoid repeat API calls.
var lastPhotoEstimate = null;     // estimate from the most recent photo scan
var shipEstCache = {};            // client-side cache: item_name -> estimate
var shipEstInFlight = {};         // de-dupe concurrent requests per item

function _shipBadgeEl(badgeId) {
  if (!badgeId) return null;
  var el = D(badgeId);
  return el;
}

function _showShipBadgeLoading(badgeId, itemName) {
  var el = _shipBadgeEl(badgeId);
  if (!el) return;
  el.style.display = 'inline-flex';
  el.innerHTML = '<span class="sb-loading"></span>Estimating ship for "' +
    (itemName.length > 28 ? itemName.slice(0, 28) + '…' : itemName) + '"…';
}

function _showShipBadgeResult(badgeId, itemName, est, opts) {
  opts = opts || {};
  var el = _shipBadgeEl(badgeId);
  if (!el) return;
  el.style.display = 'inline-flex';
  var range = '$' + FMT(est.low_usd) + ' – $' + FMT(est.high_usd);
  var serviceTxt = (est.carrier || '') + (est.service ? ' ' + est.service : '');
  var confIcon = est.confidence === 'high' ? '🟢' : (est.confidence === 'medium' ? '🟡' : '⚪');
  var suffix = opts.fallback ? ' (heuristic)' : (opts.cached ? ' (cached)' : '');
  el.innerHTML =
    confIcon + ' 📦 AI est. ' + range +
    ' · mid $' + FMT(est.mid_usd) +
    (serviceTxt ? ' · ' + serviceTxt : '') +
    suffix +
    ' <span class="sb-clear" title="Clear estimate">✕</span>';
  var clr = el.querySelector('.sb-clear');
  if (clr) {
    clr.onclick = function(ev) {
      ev.stopPropagation();
      el.style.display = 'none';
      el.innerHTML = '';
    };
  }
  el.title = (est.reasoning || 'AI shipping estimate') +
    '\nLow: $' + FMT(est.low_usd) +
    '\nMid: $' + FMT(est.mid_usd) +
    '\nHigh: $' + FMT(est.high_usd) +
    (est.weight_lb_estimate ? '\nWeight: ~' + FMT(est.weight_lb_estimate) + ' lb' : '') +
    '\n\nClick ✕ to clear.';
}

function _showShipBadgeError(badgeId, msg) {
  var el = _shipBadgeEl(badgeId);
  if (!el) return;
  el.style.display = 'inline-flex';
  el.style.background = 'rgba(248,113,113,.12)';
  el.style.borderColor = 'rgba(248,113,113,.35)';
  el.style.color = 'var(--r)';
  el.innerHTML = '❌ ' + (msg || 'Estimate failed') +
    ' <span class="sb-clear" title="Dismiss">✕</span>';
  var clr = el.querySelector('.sb-clear');
  if (clr) {
    clr.onclick = function(ev) {
      ev.stopPropagation();
      el.style.display = 'none';
      el.innerHTML = '';
      // Reset inline style overrides for next attempt
      el.style.background = '';
      el.style.borderColor = '';
      el.style.color = '';
    };
  }
}

function _resetShipBadge(badgeId) {
  var el = _shipBadgeEl(badgeId);
  if (!el) return;
  el.style.display = 'none';
  el.innerHTML = '';
  el.style.background = '';
  el.style.borderColor = '';
  el.style.color = '';
}

/**
 * Estimate shipping cost for an item via Gemini.
 *
 * @param {Object} opts
 *   itemName    {string}  required — the product name
 *   shipFieldId {string}  required — id of the <input> to populate with mid_usd
 *   badgeId     {string}  optional — id of the badge element to show estimate
 *   weightLbs   {number}  optional — user-provided weight
 *   dimensions  {string}  optional — user-provided "L×W×H in"
 *   onSuccess   {fn}      optional — called with the estimate object
 *   quiet       {boolean} optional — skip showing the loading badge
 */
async function estimateShipping(opts) {
  opts = opts || {};
  var itemName = (opts.itemName || '').trim();
  var shipFieldId = opts.shipFieldId;
  var badgeId = opts.badgeId;
  if (!itemName) {
    if (badgeId) _showShipBadgeError(badgeId, 'No item name');
    return null;
  }
  if (!shipFieldId || !D(shipFieldId)) {
    if (badgeId) _showShipBadgeError(badgeId, 'No target field');
    return null;
  }

  // Client cache hit?
  var cacheKey = itemName.toLowerCase() + '|' + (opts.weightLbs || '') + '|' + (opts.dimensions || '');
  var cached = shipEstCache[cacheKey];
  if (cached && Date.now() - cached._ts < 24 * 3600 * 1000) {
    _applyShipValue(shipFieldId, cached.mid_usd);
    if (badgeId) _showShipBadgeResult(badgeId, itemName, cached, { cached: true });
    if (opts.onSuccess) opts.onSuccess(cached);
    return cached;
  }

  // In-flight de-dupe
  if (shipEstInFlight[cacheKey]) {
    try { await shipEstInFlight[cacheKey]; } catch (e) {}
    var after = shipEstCache[cacheKey];
    if (after && Date.now() - after._ts < 24 * 3600 * 1000) {
      _applyShipValue(shipFieldId, after.mid_usd);
      if (badgeId) _showShipBadgeResult(badgeId, itemName, after, { cached: true });
      if (opts.onSuccess) opts.onSuccess(after);
      return after;
    }
  }

  if (badgeId && !opts.quiet) _showShipBadgeLoading(badgeId, itemName);

  var payload = { item_name: itemName };
  if (opts.weightLbs) payload.weight_lb = opts.weightLbs;
  if (opts.dimensions) payload.dimensions = opts.dimensions;

  var p = (async function() {
    var r = await fetch('/api/estimate-shipping', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    var d = await r.json();
    if (!r.ok) throw new Error(d.error || ('HTTP ' + r.status));
    var est = d.estimate || {};
    est._ts = Date.now();
    est._cached = !!d.cached;
    est._fallback = !!d.fallback;
    shipEstCache[cacheKey] = est;
    return { estimate: est, raw: d };
  })();
  shipEstInFlight[cacheKey] = p;
  try {
    var result = await p;
    var est = result.estimate;
    _applyShipValue(shipFieldId, est.mid_usd);
    if (badgeId) _showShipBadgeResult(badgeId, itemName, est, {
      cached: !!result.raw.cached, fallback: !!result.raw.fallback,
    });
    if (opts.onSuccess) opts.onSuccess(est);
    return est;
  } catch (err) {
    if (badgeId) _showShipBadgeError(badgeId, err.message || 'Network error');
    return null;
  } finally {
    delete shipEstInFlight[cacheKey];
  }
}

// Sets a ship input value, dispatching 'change' so recalcFromExistingData()
// runs — while preventing the change handler from clearing our AI badge.
function _applyShipValue(fieldId, value) {
  var el = D(fieldId);
  if (!el) return;
  _aiFillingShip = true;
  try {
    el.value = FMT(value);
    el.dispatchEvent(new Event('change'));
  } finally {
    _aiFillingShip = false;
  }
}

// Wire up the manual "📦 Estimate" buttons (search + quick deal pages)
function _wireShipEstButtons() {
  if (D('shipEstBtn')) {
    D('shipEstBtn').onclick = function() {
      var q = D('q').value.trim();
      if (!q) {
        _showShipBadgeError('shipEstBadge', 'Type an item first');
        return;
      }
      estimateShipping({
        itemName: q,
        shipFieldId: 'ship',
        badgeId: 'shipEstBadge',
        weightLbs: parseFloat(D('shipWeight').value) || undefined,
        dimensions: D('shipDims').value.trim() || undefined,
      });
    };
  }
  if (D('qdsEstBtn')) {
    D('qdsEstBtn').onclick = function() {
      var q = D('qd').value.trim();
      if (!q) {
        _showShipBadgeError('qdsEstBadge', 'Type an item first');
        return;
      }
      estimateShipping({
        itemName: q,
        shipFieldId: 'qds',
        badgeId: 'qdsEstBadge',
      });
    };
  }
  // When the user manually edits ship weight/dims, reset the badge so they re-estimate
  if (D('shipWeight')) {
    D('shipWeight').oninput = function() { _resetShipBadge('shipEstBadge'); };
  }
  if (D('shipDims')) {
    D('shipDims').oninput = function() { _resetShipBadge('shipEstBadge'); };
  }
}

async function recalcAfterManualDelete() {
  if (!data) return;
  try {
    ld(true);
    var r = await fetch('/api/recalculate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({data: data})
    });
    var d = await r.json();
    if (!r.ok) throw new Error(d.error || 'Recalculate failed');
    data = d;
    renderAll(data);
  } catch(e) {
    er(e.message || 'Could not recalculate after removing listing');
  } finally {
    ld(false);
  }
}

function removeListing(kind, idx, ev) {
  if (ev) { ev.preventDefault(); ev.stopPropagation(); }
  if (!data) return;
  var arr = kind === 'sold' ? (data.recent_sold || []) : (data.active_listings || []);
  if (idx < 0 || idx >= arr.length) return;
  arr.splice(idx, 1);
  if (kind === 'sold') data.recent_sold = arr; else data.active_listings = arr;
  recalcAfterManualDelete();
}

// Category search
var catTimeout = null;
async function fetchCategories() {
  var q = D('catSearch').value.trim();
  if (!q) { D('catSug').style.display = 'none'; return; }
  try {
    var r = await fetch('/api/categories?q=' + encodeURIComponent(q));
    var d = await r.json();
    if (!r.ok) throw new Error(d.error || 'Failed');
    var sug = D('catSug');
    sug.innerHTML = '';
    if (!d.suggestions || !d.suggestions.length) { sug.style.display = 'none'; return; }
    for (var i = 0; i < d.suggestions.length; i++) {
      var s = d.suggestions[i];
      var cat = s.category || {};
      var div = EL('div', '', sug);
      div.style.cssText = 'padding:8px 10px;cursor:pointer;font-size:.78rem;border-bottom:1px solid var(--b)';
      div.textContent = (cat.categoryName || 'Unknown') + (cat.categoryPath ? ' \u2014 ' + cat.categoryPath : '');
      div.onmousedown = (function(id, name) { return function() {
        D('catSearch').value = name;
        D('catId').value = id;
        D('catSug').style.display = 'none';
      }; })(cat.categoryId, cat.categoryName);
    }
    sug.style.display = 'block';
  } catch(e) { D('catSug').style.display = 'none'; }
}
D('catSearch').oninput = function() {
  if (catTimeout) clearTimeout(catTimeout);
  catTimeout = setTimeout(fetchCategories, 250);
};
D('catSearch').onblur = function() { setTimeout(function() { D('catSug').style.display = 'none'; }, 200); };
D('catSearch').onfocus = function() { if (D('catSearch').value.trim()) fetchCategories(); };

function renderAll(d) {
  var res = D('res');
  res.innerHTML = '';
  
  var actionRow = EL('div', 'rw mb1', res);
  actionRow.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;background:var(--s);padding:12px 16px;border-radius:var(--rad);border:1px solid var(--b)';
  var infoLeft = EL('div', '', actionRow);
  EL('h3', '', infoLeft).textContent = '🔍 ' + (d.query || D('q').value || 'Search Results');
  var saveBtn = EL('button', 'bt bt-p', actionRow);
  saveBtn.style.cssText = 'padding:10px 18px;font-size:0.88rem';
  saveBtn.textContent = '⭐ Save Search & Comps';
  saveBtn.onclick = function() { saveSearchAndComps(d); };

  var sumGrid = EL('div', 'gd', res);
  buildSummary(sumGrid, d);
  buildDataSource(res, d);
  buildConditions(res, d);
  buildSaturation(res, d);
  buildFlip(res, d);
  buildPromotedImpact(res, d);
  buildListings(res, d);
  buildVerification(res, d);
}

function addStatCard(grid, label, value, sub, cls) {
  var sc = EL('div', 'sc', grid);
  EL('div', 'lb', sc).textContent = label;
  var vl = EL('div', 'vl', sc);
  vl.textContent = value;
  if (cls) vl.classList.add(cls);
  EL('div', 'sm', sc).textContent = sub;
}

function buildSummary(grid, d) {
  var s = d.sold_summary;
  var a = d.active_summary;
  var f = d.flip_analysis || {};
  var fc = d.active_filter_condition || '';
  var flt = (fc && fc !== 'all') ? ' (' + CL(fc) + ')' : '';
  var p = f.potential_profit || 0;
  var pc = f.potential_profit_pct || 0;

  addStatCard(grid, '💰 Median Sold' + flt, '$' + FMT(s.median), s.count + ' sold', '');
  addStatCard(grid, '📊 Range (10th-90th)', '$' + FMT(s.p10 || s.low) + ' \u2013 $' + FMT(s.p90 || s.high), 'Min/Max $' + FMT(s.low) + ' / $' + FMT(s.high), '');
  var actCls = (a.median && s.median && a.median < s.median) ? 'g' : (a.median > s.median * 1.05 ? 'am' : '');
  addStatCard(grid, '🏷️ Active Market', '$' + (a.median ? FMT(a.median) : '--'), a.count + ' listed', actCls);
  var score = f.score || 0;
  var scCls = score >= 70 ? 'g' : (score >= 50 ? '' : (score >= 30 ? 'am' : 'r'));
  addStatCard(grid, '🔄 Flip Score', score + '/100', f.verdict || 'N/A', scCls);
  var netCls = p >= 0 ? 'g' : 'r';
  var netSub = (pc >= 0 ? '+' : '') + pc + '%' + (f.user_buy_price_used ? ' \u00b7 your price' : ' \u00b7 low sold');
  addStatCard(grid, '💵 Net Profit', (p >= 0 ? '+' : '') + '$' + FMT(p), netSub, netCls);
}

function buildTimePills(res) {
  return;
}

function buildDataSource(res, d) {
  var dr = EL('div', '', res);
  dr.style.marginBottom = '12px';
  var confidence = d.confidence || 'low';
  var confColors = {high: 'ri', medium: 'st', low: 'fa'};
  var srcBdg = EL('span', 'bdg ' + confColors[confidence], dr);
  srcBdg.textContent = d.data_source || 'Unknown';
  var confSpan = EL('span', '', dr);
  confSpan.style.cssText = 'font-size:.65rem;color:var(--t2);margin-left:6px';
  confSpan.textContent = d.confidence_label || '';
  if (d.ebay_url) {
    var verifyLink = EL('a', '', dr);
    verifyLink.href = d.ebay_url; verifyLink.target = '_blank'; verifyLink.rel = 'noopener noreferrer';
    verifyLink.style.cssText = 'margin-left:12px;font-size:.7rem;color:var(--a);text-decoration:none;font-weight:600';
    verifyLink.textContent = 'Verify on eBay Sold Search →';
  }
  if (d.market_note) {
    var noteDiv = EL('div', '', dr);
    noteDiv.style.cssText = 'font-size:.65rem;color:var(--am);margin-top:6px;padding:4px 8px;background:rgba(251,191,36,.1);border-radius:6px';
    noteDiv.textContent = d.market_note;
  }
  if (d.market_segment && d.market_segment !== 'auto') {
    var segDiv = EL('div', '', dr);
    segDiv.style.cssText = 'font-size:.65rem;color:var(--t2);margin-top:6px';
    segDiv.textContent = 'Market segment: ' + segLabel(d.market_segment);
  }
  if (d.sold_validation_summary) {
    var sv = d.sold_validation_summary;
    var reasonText = '';
    if (sv.excluded_reasons) {
      var parts = [];
      for (var rk in sv.excluded_reasons) {
        parts.push(rk.replace(/_/g, ' ') + ': ' + sv.excluded_reasons[rk]);
      }
      reasonText = parts.slice(0, 3).join(' · ');
    }
    var valDiv = EL('div', '', dr);
    valDiv.style.cssText = 'font-size:.65rem;color:var(--t2);margin-top:6px;padding:4px 8px;background:rgba(91,141,239,.08);border-radius:6px';
    var srcText = '';
    if (sv.source_breakdown) {
      var srcParts = [];
      for (var sk in sv.source_breakdown) { srcParts.push(sk.replace('eBay ', '') + ': ' + sv.source_breakdown[sk]); }
      srcText = srcParts.slice(0, 3).join(' · ');
    }
    valDiv.textContent = 'Validated sold listings: ' + (sv.valid_count || 0) + ' | Excluded: ' + (sv.excluded_count || 0) + (srcText ? ' · Sources: ' + srcText : '') + (reasonText ? ' · ' + reasonText : '');
  }
  if (d.api_missing) {
    var setupDiv = EL('div', '', dr);
    setupDiv.style.cssText = 'font-size:.65rem;color:var(--r);margin-top:6px';
    setupDiv.textContent = 'eBay API not configured. ' + (d.setup_instructions || '');
  }
}

function buildChart(res, d) {
  if (chart) { chart.destroy(); chart = null; }
  return;
}

function buildConditions(res, d) {
  var conds = d.available_conditions || [];
  if (conds.length < 2) return;
  var cs = d.condition_sold || {};
  var ca = d.condition_active || {};
  var fc = d.active_filter_condition || '';
  var cd = EL('div', 'cd', res);
  EL('h3', '', cd).textContent = '🏷️ Price by Condition';
  var tabs = EL('div', 'ctabs', cd);
  var panels = EL('div', '', cd);
  for (var i = 0; i < conds.length; i++) {
    var c = conds[i];
    var lb = CL(c);
    var isA = c === fc;
    var tab = EL('button', 'ct' + (isA ? ' ac' : ''), tabs);
    TXT(tab, lb);
    tab.onclick = (function(cc) { return function() { D('cond').value = cc; search(cc); }; })(c);
    var panel = EL('div', '', panels);
    if (!isA) panel.style.display = 'none';
    var sold = cs[c] || {low:0, median:0, high:0, mean:0, count:0};
    var act = ca[c] || {low:0, median:0, high:0, mean:0, count:0};
    var grid = EL('div', 'gd', panel);
    grid.style.marginTop = '10px';
    addStatCard(grid, 'Sold Median', '$' + FMT(sold.median), sold.count + ' sold', '');
    addStatCard(grid, 'Sold Range', '$' + FMT(sold.low) + ' \u2013 $' + FMT(sold.high), 'Avg $' + FMT(sold.mean), '');
    addStatCard(grid, 'Active Median', '$' + FMT(act.median), act.count + ' listed', '');
    if (sold.median > 0 && sold.low > 0) {
      addStatCard(grid, 'Potential', '$' + FMT(sold.median - sold.low), 'Buy low, sell median', 'g');
    }
    var fb = EL('button', 'bt bt-p', panel);
    TXT(fb, '🔍 Show ' + lb + ' Only');
    fb.onclick = (function(cc) { return function() { D('cond').value = cc; search(cc); }; })(c);
  }
}

function buildSaturation(res, d) {
  var opp = d.opportunity || {};
  var sat = opp.saturation || {};
  if (!opp.score) return;
  var cd = EL('div', 'cd', res);
  EL('h3', '', cd).textContent = '📊 Market Analysis';
  var row = EL('div', '', cd);
  row.style.cssText = 'display:flex;align-items:center;gap:12px;margin-bottom:10px';
  var oc = opp.score >= 70 ? 'gr' : (opp.score >= 50 ? 'ok' : (opp.score >= 30 ? 'wa' : 'no'));
  var fs = EL('div', 'fs ' + oc, row);
  TXT(fs, String(opp.score));
  var info = EL('div', '', row);
  var vh = EL('div', '', info);
  vh.style.cssText = 'font-weight:700;font-size:1.05rem';
  TXT(vh, opp.verdict || '');
  var vd = EL('div', '', info);
  vd.style.cssText = 'font-size:.78rem;color:var(--t2)';
  TXT(vd, opp.description || '');
  var rt = sat.active_sold_ratio || 0;
  var rp = Math.min(100, (rt / 10) * 100);
  var rc = rt < 1 ? 'var(--g)' : (rt < 3 ? 'var(--am)' : (rt < 8 ? '#f97316' : 'var(--r)'));
  var barDiv = EL('div', '', cd);
  var lbl = EL('div', '', barDiv);
  lbl.style.cssText = 'font-size:.68rem;color:var(--t2);margin-bottom:3px';
  TXT(lbl, 'Saturation: ' + (sat.label || '') + ' \u2014 ' + (sat.active_count || 0) + ' active / ' + (sat.sold_count || 0) + ' sold (' + rt.toFixed(1) + 'x)');
  var bar = EL('div', '', barDiv);
  bar.style.cssText = 'height:6px;background:var(--bg);border-radius:3px;overflow:hidden';
  var fill = EL('div', '', bar);
  fill.style.cssText = 'height:100%;width:' + rp + '%;background:' + rc + ';border-radius:3px';
}

function buildFlip(res, d) {
  var f = d.flip_analysis || {};
  if (!f.verdict) return;
  var cd = EL('div', 'cd', res);
  var row = EL('div', '', cd);
  row.style.cssText = 'display:flex;align-items:center;gap:12px;margin-bottom:12px';
  var cls = f.score >= 70 ? 'gr' : (f.score >= 50 ? 'ok' : (f.score >= 30 ? 'wa' : 'no'));
  var fs = EL('div', 'fs ' + cls, row);
  TXT(fs, String(f.score || 0));
  var info = EL('div', '', row);
  EL('h3', '', info).textContent = f.verdict;
  var det = EL('div', '', info);
  det.style.cssText = 'font-size:.78rem;color:var(--t2)';
  TXT(det, f.verdict_detail || '');
  var grid = EL('div', 'gd', cd);
  var p = f.potential_profit || 0;
  var pc = f.potential_profit_pct || 0;
  addStatCard(grid, '💵 Net Profit', (p >= 0 ? '+' : '') + '$' + FMT(p), FMT(pc) + '%', p >= 0 ? 'g' : 'r');
  addStatCard(grid, '📊 Buy \u2192 Sell', '$' + FMT(f.potential_buy_price || 0) + ' \u2192 $' + FMT(f.potential_sell_price || 0), '', '');
  addStatCard(grid, '⚡ Velocity', FMT(f.velocity_per_day || 0) + '/day', f.velocity_label || '', '');
  var liq = f.liquidity || {};
  addStatCard(grid, '⏱ Sells In', liq.avg_days_to_sell ? '~' + Math.round(liq.avg_days_to_sell) + 'd' : 'N/A', liq.label || '', '');
  addStatCard(grid, '⚠️ Risk', f.risk_level || 'N/A', '', f.risk_level === 'Low' ? 'g' : (f.risk_level === 'High' ? 'r' : 'am'));
  var fc2 = f.fee_calculation || {};
  if (fc2.platform) {
    var feeDiv = EL('div', '', cd);
    feeDiv.style.cssText = 'margin-top:10px;padding-top:10px;border-top:1px solid var(--b);font-size:.75rem;color:var(--t2)';
    TXT(feeDiv, '\ud83d\udccb ' + fc2.platform + ' FVF ' + fc2.fvf_pct + '% = $' + FMT(fc2.fvf) + ' | Total fees: $' + FMT(fc2.total_fees) + (fc2.shipping_cost > 0 ? ' | Ship: $' + FMT(fc2.shipping_cost) : '') + ' | Net: $' + FMT(fc2.net_profit));
  }
}

function buildPromotedImpact(res, d) {
  var pi = d.promoted_impact || [];
  if (!pi.length) return;
  var cd = EL('div', 'cd', res);
  EL('h3', '', cd).textContent = '📢 Promoted Listings Impact';
  var sub = EL('div', 'sb', cd);
  sub.textContent = 'How eBay ad rates affect your net profit.';
  var grid = EL('div', 'gd', cd);
  for (var i = 0; i < pi.length; i++) {
    var r = pi[i];
    var isRec = r.rate === 0 ? 'Recommended' : '';
    var cls = r.net_profit >= 0 ? 'g' : 'r';
    addStatCard(grid, r.rate + '% Ad Rate' + (isRec ? ' ⭐' : ''), (r.net_profit >= 0 ? '+' : '') + '$' + FMT(r.net_profit), 'Ad cost: $' + FMT(r.promoted_fee), cls);
  }
}

function buildListings(res, d) {
  var sH = EL('h3', '', res);
  sH.style.cssText = 'font-size:.95rem;margin-bottom:10px';
  TXT(sH, '🟢 Verified Sold Listings');
  if (d.recent_sold && d.recent_sold.length) {
    var sCount = EL('div', 'lcount', res);
    var excludedCount = d.sold_validation_summary ? (d.sold_validation_summary.excluded_count || 0) : 0;
    TXT(sCount, d.recent_sold.length + ' validated sold comps used in the average.' + (excludedCount ? ' ' + excludedCount + ' sold candidates were excluded from pricing.' : '') + ' Click a row to verify on eBay sold search; click ❌ to remove a comp manually.');
    var sBox = EL('div', 'lscroll', res);
    for (var i = 0; i < d.recent_sold.length; i++) {
      var it = d.recent_sold[i];
      var row = EL('div', 'lr', sBox);
      row.onclick = (function(u) { return function() { window.open(u, '_blank'); }; })(it.verification_url || d.ebay_url || it.url || '#');
      var del = EL('button', 'xdel', row);
      del.type = 'button'; del.title = 'Remove this sold comp'; del.textContent = '❌';
      del.onclick = (function(ix) { return function(ev) { removeListing('sold', ix, ev); }; })(i);
      var tit = EL('span', 'it', row);
      TXT(tit, it.title || '');
      if (it.condition) { var ic = EL('span', 'ic', row); TXT(ic, CL(it.condition)); }
      var id = EL('span', 'id', row); TXT(id, it.sold_date || '');
      var ip = EL('span', 'ip', row); TXT(ip, '$' + FMT(it.price));
      var src = EL('span', 'id', row);
      src.style.marginLeft = '6px';
      TXT(src, it.source === 'eBay Sold Search' ? 'Sold Search' : (it.source === 'eBay Finding API' ? 'Finding' : (it.source === 'eBay Browse API' ? 'Browse' : (it.source || ''))));
      if (it.url) {
        var raw = EL('a', '', row);
        raw.href = it.url;
        raw.target = '_blank';
        raw.rel = 'noopener noreferrer';
        raw.textContent = 'Listing';
        raw.style.cssText = 'font-size:.68rem;color:var(--a);margin-left:8px;text-decoration:none';
        raw.onclick = function(ev) { ev.stopPropagation(); };
        raw.title = 'Open original eBay listing page (buyer-facing page, not proof of sold status)';
      }
    }
  } else {
    var emp = EL('div', '', res);
    emp.style.cssText = 'text-align:center;padding:30px;color:var(--t2);font-size:.82rem';
    TXT(emp, 'No validated eBay sold comps available.');
    if (d.sold_validation_summary && d.sold_validation_summary.excluded_count) {
      var sub = EL('div', '', res);
      sub.style.cssText = 'text-align:center;padding:0 20px 24px;color:var(--am);font-size:.76rem';
      TXT(sub, d.sold_validation_summary.excluded_count + ' sold candidates were excluded from pricing because they had missing/future sold dates or also appeared active.');
    }
  }
  var aH = EL('h3', '', res);
  aH.style.cssText = 'font-size:.95rem;margin-bottom:10px;margin-top:20px';
  TXT(aH, '🔵 Active Listings');
  if (d.active_listings && d.active_listings.length) {
    var aCount = EL('div', 'lcount', res);
    TXT(aCount, d.active_listings.length + ' active comps used in the market analysis. Scroll to review all; click ❌ to remove bad comps.');
    var aBox = EL('div', 'lscroll', res);
    for (var i = 0; i < d.active_listings.length; i++) {
      var it = d.active_listings[i];
      var row = EL('div', 'lr', aBox);
      row.onclick = (function(u) { return function() { window.open(u, '_blank'); }; })(it.url || '#');
      var del = EL('button', 'xdel', row);
      del.type = 'button'; del.title = 'Remove this active comp'; del.textContent = '❌';
      del.onclick = (function(ix) { return function(ev) { removeListing('active', ix, ev); }; })(i);
      var tit = EL('span', 'it', row); TXT(tit, it.title || '');
      if (it.condition) { var ic = EL('span', 'ic', row); TXT(ic, CL(it.condition)); }
      var ip = EL('span', 'ip', row); TXT(ip, '$' + FMT(it.price));
    }
  } else {
    var emp = EL('div', '', res);
    emp.style.cssText = 'text-align:center;padding:30px;color:var(--t2);font-size:.82rem';
    TXT(emp, 'No eBay active listings found.');
  }
}

function buildVerification(res, d) {
  var recentSold = d.recent_sold || [];
  var vc = EL('div', 'cd', res);
  EL('h3', '', vc).textContent = '🔍 Verify Prices';
  var sub = EL('div', 'sb', vc);
  sub.textContent = 'Always verify before buying. eBay prices change fast.';
  var q = encodeURIComponent(d.query);
  var links = [
    {name:'eBay Sold', url:'https://www.ebay.com/sch/i.html?_nkw=' + q + '&LH_Sold=1&LH_Complete=1', icon:'🔗'},
    {name:'eBay Active', url:'https://www.ebay.com/sch/i.html?_nkw=' + q, icon:'🔍'},
  ];
  if (_isGaming(d.query)) {
    links.push({name:'PriceCharting', url:'https://www.pricecharting.com/search-products?q=' + q, icon:'🎮'});
  }
  var linkGrid = EL('div', '', vc);
  linkGrid.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px';
  for (var i = 0; i < links.length; i++) {
    var link = links[i];
    var a = EL('a', 'bt bt-g', linkGrid);
    a.href = link.url; a.target = '_blank'; a.textContent = link.icon + ' ' + link.name;
    a.style.textDecoration = 'none';
  }
  if (recentSold.length > 0) {
    var sampleItems = recentSold.slice(0, 5);
    sampleItems.forEach(function(item) {
      var itemRow = EL('div', 'lr', vc);
      var info = EL('div', 'it', itemRow);
      var title = item.title || 'Unknown item';
      info.textContent = title.substring(0, 50) + (title.length > 50 ? '...' : '');
      var price = EL('div', 'ip', itemRow);
      price.textContent = item.price ? '$' + item.price.toFixed(2) : '';
      var cond = EL('span', 'ic', itemRow);
      cond.textContent = item.condition || '';
      var date = EL('div', 'id', itemRow);
      date.textContent = item.sold_date || '';
    });
  }
}

function _isGaming(q) {
  var gaming = ["nintendo","switch","playstation","ps5","ps4","ps3","xbox","pokemon","mario","zelda","gameboy","wii","sega","atari","gamecube","ds","3ds","amiibo","nes","snes","n64","dreamcast","genesis"];
  var ql = (q || '').toLowerCase();
  return gaming.some(function(k) { return ql.indexOf(k) !== -1; });
}

// Quick Deal
D('qdg').onclick = rqd;
D('qd').onkeydown = function(e) { if (e.key === 'Enter') rqd(); };
async function rqd() {
  var inp = D('qd').value.trim();
  if (!inp) return;
  var st = D('qdst').value || 'none';
  var sh = parseFloat(D('qds').value) || 0;
  var seg = D('qdSeg') ? (D('qdSeg').value || 'auto') : 'auto';
  D('qdg').textContent = '...';
  try {
    var r = await fetch('/api/quick-deal?input=' + encodeURIComponent(inp) + '&store_tier=' + st + '&shipping=' + sh.toFixed(2) + '&market_segment=' + encodeURIComponent(seg));
    var respData = await r.json();
    if (!r.ok) throw new Error(respData.error || 'Failed');
    var d = respData;
    var isB = d.verdict === 'BUY';
    var isM = d.verdict === 'MAYBE';
    var bc = isB ? 'var(--g)' : (isM ? 'var(--am)' : 'var(--r)');
    var bg = isB ? 'rgba(52,211,153,.08)' : (isM ? 'rgba(251,191,36,.08)' : 'rgba(248,113,113,.08)');
    var qdr = D('qdr');
    qdr.innerHTML = '';
    var wrap = EL('div', '', qdr);
    wrap.style.cssText = 'background:' + bg + ';border:2px solid ' + bc + ';border-radius:var(--rad);padding:24px;margin-top:14px;text-align:center';
    var big = EL('div', '', wrap);
    big.style.cssText = 'font-size:2.2rem;margin-bottom:6px';
    TXT(big, d.verdict_label);
    var reason = EL('div', '', wrap);
    reason.style.cssText = 'color:' + bc + ';font-weight:700;margin-bottom:12px';
    TXT(reason, d.verdict_reason);
    var grid = EL('div', 'gd', wrap);
    grid.style.textAlign = 'left';
    addStatCard(grid, '🏷️ Found', d.item_name, d.detected_condition_label, '');
    addStatCard(grid, '💵 Your Price', d.your_price ? '$' + d.your_price.toFixed(2) : '--', 'Market: ' + d.market_value_range, '');
    addStatCard(grid, '💰 Net', d.net_profit_display, d.net_margin + '%', (d.net_profit || 0) >= 0 ? 'g' : 'r');
    addStatCard(grid, '⏱ Sells In', '~' + Math.round(d.days_to_sell) + 'd', d.velocity_label, '');
    addStatCard(grid, '📊 Score', d.flip_score + '/100', '', '');
    if (d.full_result) {
      var fb = EL('button', 'bt bt-p mt1', wrap);
      TXT(fb, '📊 Full Analysis');
      fb.onclick = function() {
        data = d.full_result;
        if (d.your_price) D('bp').value = d.your_price;
        D('ship').value = parseFloat(D('qds').value) || 0;
        D('storeTier').value = D('qdst').value;
        D('q').value = d.item_name || '';
        if (d.detected_condition) D('cond').value = d.detected_condition;
        if (D('marketSeg') && D('qdSeg')) D('marketSeg').value = D('qdSeg').value || 'auto';
        D('promo').value = '0';  // reset ad rate for fresh analysis in search
        showPage('search');
        if (data) renderAll(data);
      };
    }
    if (token && d.verdict) {
      try {
        await fetch('/api/deal-history?token=' + getToken(), {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({item_name:d.item_name, detected_condition:d.detected_condition, your_price:d.your_price, market_median:d.market_median, net_profit:d.net_profit, flip_score:d.flip_score, verdict:d.verdict})
        });
      } catch(e) {}
    }
  } catch(err) {
    D('qdr').innerHTML = '<div class="er on">' + err.message + '</div>';
  }
  D('qdg').textContent = 'Analyze';
}

function showToast(msg, type) {
  var tc = D('toastContainer');
  if (!tc) return;
  var el = document.createElement('div');
  el.className = 'toast ' + (type || 'info');
  var icon = type === 'success' ? '✅ ' : (type === 'error' ? '❌ ' : 'ℹ️ ');
  el.textContent = icon + msg;
  tc.appendChild(el);
  setTimeout(function() {
    el.style.opacity = '0';
    el.style.transition = 'opacity 0.3s';
    setTimeout(function() { if (el.parentNode) el.parentNode.removeChild(el); }, 300);
  }, 3000);
}

async function saveSearchAndComps(d) {
  if (!token) {
    showToast('Login required to bookmark searches', 'info');
    SHOW('authOv');
    return;
  }
  var payload = {
    query: d.query || D('q').value.trim(),
    condition: D('cond').value || 'all',
    buy_price: parseFloat(D('bp').value) || 0,
    market_median: (d.sold_summary && d.sold_summary.median) || 0,
    net_profit: (d.flip_analysis && d.flip_analysis.potential_profit) || 0,
    flip_score: (d.flip_analysis && d.flip_analysis.score) || 0,
    listings_json: JSON.stringify((d.recent_sold || []).slice(0, 10))
  };
  try {
    var r = await fetch('/api/saved-searches?token=' + getToken(), {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    if (r.ok) {
      showToast('Search & listing comps saved to your account!', 'success');
      loadSavedSearches();
    } else {
      showToast('Could not save search', 'error');
    }
  } catch(e) { showToast('Network error', 'error'); }
}

async function loadSavedSearches() {
  var container = D('savedSearchList');
  if (!container) return;
  if (!token) {
    container.innerHTML = '<div class="empty-state"><h3>👤 Login Required</h3><p>Log in to bookmark specific item searches and listing comps.</p><button class="bt bt-p" onclick="SHOW(\'authOv\')">Log In / Sign Up</button></div>';
    return;
  }
  try {
    var items = await fetch('/api/saved-searches?token=' + getToken()).then(function(r) { return r.json(); });
    if (!items || !items.length) {
      container.innerHTML = '<div class="empty-state"><h3>⭐ No Bookmarked Searches Yet</h3><p>Search for any item and click \'⭐ Save Search & Comps\' to bookmark results here.</p><button class="bt bt-p" onclick="showPage(\'search\')">🔍 Run a Search</button></div>';
      return;
    }
    container.innerHTML = '';
    for (var i = 0; i < items.length; i++) {
      (function(it) {
        var card = document.createElement('div');
        card.className = 'cd mb1';
        card.style.cssText = 'padding:16px;border:1px solid var(--b);border-radius:var(--rad);background:var(--s);text-align:left';
        
        var top = document.createElement('div');
        top.style.cssText = 'display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px;gap:8px';
        var titleWrap = document.createElement('div');
        titleWrap.innerHTML = '<h3 style="font-size:1.05rem;color:var(--t);margin:0">' + esc(it.query) + '</h3><small style="color:var(--t2);font-size:0.75rem">Saved ' + (it.created_at ? esc(it.created_at).slice(0, 16) : 'recently') + ' · Cond: ' + CL(it.condition) + '</small>';
        top.appendChild(titleWrap);

        var del = document.createElement('button');
        del.className = 'bt bt-g';
        del.style.cssText = 'padding:4px 10px;font-size:0.75rem';
        del.textContent = '✕';
        del.onclick = async function() {
          await fetch('/api/saved-searches/' + it.id + '?token=' + getToken(), {method:'DELETE'});
          showToast('Saved search deleted', 'info');
          loadSavedSearches();
        };
        top.appendChild(del);
        card.appendChild(top);

        var stats = document.createElement('div');
        stats.style.cssText = 'display:flex;gap:12px;margin:10px 0;background:var(--s2);padding:10px;border-radius:var(--rs);font-size:0.85rem;flex-wrap:wrap';
        stats.innerHTML = '<div><span style="color:var(--t2);font-size:0.75rem;display:block">Market Median</span><strong>$' + FMT(it.market_median) + '</strong></div>' +
                          '<div><span style="color:var(--t2);font-size:0.75rem;display:block">Net Profit</span><strong style="color:' + (it.net_profit >= 0 ? 'var(--g)' : 'var(--r)') + '">' + (it.net_profit >= 0 ? '+' : '') + '$' + FMT(it.net_profit) + '</strong></div>' +
                          '<div><span style="color:var(--t2);font-size:0.75rem;display:block">Flip Score</span><strong>' + it.flip_score + '/100</strong></div>';
        card.appendChild(stats);

        var rerun = document.createElement('button');
        rerun.className = 'bt bt-p mt1';
        rerun.style.cssText = 'width:100%;padding:10px;font-size:0.88rem';
        rerun.textContent = '🔄 Re-run Live Market Search';
        rerun.onclick = function() {
          D('q').value = it.query;
          if (it.buy_price) D('bp').value = it.buy_price;
          if (it.condition) D('cond').value = it.condition;
          showPage('search'); search();
        };
        card.appendChild(rerun);

        try {
          var comps = JSON.parse(it.listings_json || '[]');
          if (comps && comps.length) {
            var compDetails = document.createElement('details');
            compDetails.style.cssText = 'margin-top:10px;border-top:1px solid var(--b);padding-top:8px;font-size:0.8rem';
            compDetails.innerHTML = '<summary style="cursor:pointer;color:var(--a);font-weight:600">📋 View Saved Comps Snapshot (' + comps.length + ' sold listings)</summary>' +
                                    '<div style="margin-top:8px;max-height:200px;overflow-y:auto">' +
                                    comps.map(function(c) { return '<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px dashed var(--b)"><span>' + esc(c.title || '') + '</span><strong>$' + FMT(c.price || 0) + '</strong></div>'; }).join('') +
                                    '</div>';
            card.appendChild(compDetails);
          }
        } catch(e) {}

        container.appendChild(card);
      })(items[i]);
    }
  } catch(e) { container.innerHTML = '<div style="text-align:center;padding:30px;color:var(--r)">Could not load saved searches.</div>'; }
}

// Watchlist
async function loadWl() {
  if (!token) { D('wl').innerHTML = '<div class="empty-state"><h3>👤 Login Required</h3><p>Log in to monitor market prices and track items.</p><button class="bt bt-p" onclick="SHOW(\'authOv\')">Log In / Sign Up</button></div>'; return; }
  try {
    var items = await fetch('/api/watchlist?token=' + getToken()).then(function(r) { return r.json(); });
    if (!items || !items.length) { D('wl').innerHTML = '<div class="empty-state"><h3>⭐ No Tracked Items Yet</h3><p>Search for any product and click \'Track Price\' to monitor market value.</p><button class="bt bt-p" onclick="showPage(\'search\')">🔍 Start Searching</button></div>'; return; }
    D('wl').innerHTML = '';
    for (var i = 0; i < items.length; i++) {
      var it = items[i];
      var row = EL('div', 'lr', D('wl'));
      var tit = EL('span', 'it', row); tit.style.fontWeight = '600'; TXT(tit, it.query);
      var ip = EL('span', 'ip', row); TXT(ip, '$' + FMT(it.last_median));
      var chg = (it.price_change_pct || 0);
      var cs = EL('span', '', row); cs.style.cssText = 'font-size:.7rem;color:' + (chg > 0 ? 'var(--g)' : (chg < -10 ? 'var(--r)' : 'var(--t2)'));
      TXT(cs, (chg > 0 ? '+' : '') + chg.toFixed(1) + '%');
      var del = EL('button', 'bt bt-g', row); del.style.cssText = 'padding:3px 8px;font-size:.65rem'; TXT(del, '✕');
      del.onclick = (function(id) { return function() { delWl(id); }; })(it.id);
    }
  } catch(e) { D('wl').innerHTML = '<div style="text-align:center;padding:30px;color:var(--t2)">Could not load.</div>'; }
}
async function delWl(id) { await fetch('/api/watchlist/' + id + '?token=' + getToken(), {method:'DELETE'}); loadWl(); showToast('Item removed from watchlist', 'info'); }
D('wref').onclick = async function() { await fetch('/api/watchlist/refresh-all?token=' + getToken(), {method:'POST'}); loadWl(); showToast('Watchlist refreshed', 'success'); };

// Inventory
D('invAdd').onclick = function() { SHOW('invOv'); };
async function loadInv() {
  if (!token) { D('inv').innerHTML = '<div class="empty-state"><h3>👤 Login Required</h3><p>Log in to track your flipping inventory and deals.</p><button class="bt bt-p" onclick="SHOW(\'authOv\')">Log In / Sign Up</button></div>'; return; }
  try {
    var r1 = await fetch('/api/inventory?token=' + getToken());
    var r2 = await fetch('/api/inventory/stats?token=' + getToken());
    var items = await r1.json();
    var s = await r2.json();
    if (s) {
      D('invStats').innerHTML = '';
      addStatCard(D('invStats'), '📦 Items', String(s.total_items), '$' + FMT(s.total_cost) + ' invested', '');
      addStatCard(D('invStats'), '📝 Listed', String(s.listed), '', '');
      addStatCard(D('invStats'), '💰 Sold', String(s.sold), '$' + FMT(s.sold_revenue) + ' revenue', '');
      addStatCard(D('invStats'), '💵 Profit', ((s.sold_profit || 0) >= 0 ? '+' : '') + '$' + FMT(s.sold_profit), '', (s.sold_profit || 0) >= 0 ? 'g' : 'r');
    }
    if (!items || !items.length) { D('inv').innerHTML = '<div class="empty-state"><h3>📦 No Inventory Items Yet</h3><p>Track your inventory purchases, listings, and sales profits.</p><button class="bt bt-p" onclick="D(\'invAdd\').click()">+ Track Your First Item</button></div>'; return; }
    D('inv').innerHTML = '';
    for (var i = 0; i < items.length; i++) {
      var it = items[i];
      var st = it.status;
      var pf = (it.sold_price || 0) - (it.buy_price || 0);
      var row = EL('div', 'lr', D('inv'));
      EL('span', '', row).textContent = st === 'bought' ? '📦' : (st === 'listed' ? '📝' : '💰');
      var tit = EL('span', 'it', row); tit.style.fontWeight = '600'; TXT(tit, it.item_name);
      var ic = EL('span', 'ic', row); TXT(ic, it.condition || '');
      var ip = EL('span', 'ip', row); TXT(ip, '$' + FMT(it.buy_price));
      if (st === 'sold') {
        var pfSpan = EL('span', '', row);
        pfSpan.style.cssText = 'color:' + (pf >= 0 ? 'var(--g)' : 'var(--r)') + ';font-weight:700';
        TXT(pfSpan, (pf >= 0 ? '+' : '') + '$' + FMT(pf));
      } else { EL('span', 'id', row).textContent = st; }
      var del = EL('button', 'bt bt-g', row); del.style.cssText = 'padding:3px 8px;font-size:.65rem'; TXT(del, '✕');
      del.onclick = (function(id) { return function() { delInv(id); }; })(it.id);
    }
  } catch(e) { D('inv').innerHTML = '<div style="text-align:center;padding:30px;color:var(--t2)">Could not load.</div>'; }
}
async function delInv(id) { await fetch('/api/inventory/' + id + '?token=' + getToken(), {method:'DELETE'}); loadInv(); showToast('Inventory item deleted', 'info'); }
D('isave').onclick = async function() {
  var b = {item_name:D('in').value.trim(), buy_price:parseFloat(D('ibp').value)||0, platform:'ebay', condition:D('icond').value.trim(), status:D('istat').value, sold_price:parseFloat(D('isp').value)||0};
  if (!b.item_name) return;
  await fetch('/api/inventory?token=' + getToken(), {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(b)});
  HIDE('invOv'); loadInv(); showToast('Item saved to inventory', 'success');
};
D('csvBtn').onclick = async function() {
  var items = await fetch('/api/inventory?token=' + getToken()).then(function(r) { return r.json(); });
  var csv = 'Item,Condition,Buy,Status,Sold,Profit\n' + items.map(function(it) { return '"' + it.item_name + '","' + it.condition + '",' + it.buy_price + ',' + it.status + ',' + it.sold_price + ',' + ((it.sold_price||0) - it.buy_price); }).join('\n');
  var b = new Blob([csv], {type:'text/csv'});
  var a = document.createElement('a');
  a.href = URL.createObjectURL(b); a.download = 'inventory.csv'; a.click();
  showToast('Inventory CSV downloaded', 'success');
};

// Lot Calculator
var LZ = [];
function rLot() {
  D('litems').innerHTML = '';
  for (var i = 0; i < LZ.length; i++) {
    var row = EL('div', 'lr', D('litems'));
    row.style.cssText = 'display:flex;justify-content:space-between;align-items:center;padding:8px 12px;background:var(--s);border:1px solid var(--b);border-radius:var(--rs);margin-bottom:6px';
    var nm = EL('span', '', row); nm.style.fontWeight = '600'; TXT(nm, LZ[i].name);
    var rightGrp = EL('div', '', row); rightGrp.style.cssText = 'display:flex;align-items:center;gap:12px';
    if (LZ[i].price > 0) { var pr = EL('span', 'ip', rightGrp); TXT(pr, '$' + LZ[i].price.toFixed(2)); }
    var del = EL('button', 'bt bt-g', rightGrp); del.style.cssText = 'padding:2px 8px;font-size:.65rem'; TXT(del, '✕');
    del.onclick = (function(idx) { return function() { LZ.splice(idx,1); rLot(); }; })(i);
  }
}
D('ladd').onclick = function() {
  var n = D('li').value.trim();
  var p = parseFloat(D('lp').value) || 0;
  if (!n) return;
  LZ.push({name:n, price:p}); D('li').value = ''; D('lp').value = ''; rLot();
  D('li').focus();
};
D('li').onkeydown = function(e) { if (e.key === 'Enter') D('ladd').onclick(); };
D('lclear').onclick = function() { LZ.length = 0; D('lres').innerHTML = ''; rLot(); };
D('lcalc').onclick = async function() {
  if (!LZ.length) return;
  var st = D('lst').value || 'none';
  var sh = parseFloat(D('lship').value) || 0;
  var tCost = parseFloat(D('ltotalCost').value) || 0;
  D('lcalc').textContent = '...';
  try {
    var r = await fetch('/api/lot-calculate', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({items:LZ, store_tier:st, shipping_per_item:sh, total_lot_cost:tCost})});
    var d = await r.json();
    if (!r.ok) throw new Error(d.error || 'Failed');
    var c = d.verdict_color === 'green' ? 'var(--g)' : (d.verdict_color === 'amber' ? 'var(--am)' : 'var(--r)');
    var bg = d.verdict_color === 'green' ? 'rgba(52,211,153,.08)' : (d.verdict_color === 'amber' ? 'rgba(251,191,36,.08)' : 'rgba(248,113,113,.08)');
    D('lres').innerHTML = '';
    var wrap = EL('div', '', D('lres'));
    wrap.style.cssText = 'background:' + bg + ';border:2px solid ' + c + ';border-radius:var(--rad);padding:20px;margin-top:14px;text-align:center';
    var big = EL('div', '', wrap);
    big.style.cssText = 'font-size:1.8rem;color:' + c + ';font-weight:800';
    TXT(big, d.verdict);
    var grid = EL('div', 'gd', wrap);
    grid.style.cssText = 'margin-top:10px;text-align:left';
    addStatCard(grid, 'Asking Cost', '$' + FMT(d.total_cost), tCost > 0 ? 'Custom overall lot cost' : 'Sum of items + shipping', '');
    addStatCard(grid, 'Market Value', '$' + FMT(d.total_market_value), LZ.length + ' items overall', '');
    addStatCard(grid, 'Est. Net Profit', ((d.total_profit||0) >= 0 ? '+' : '') + '$' + FMT(d.total_profit), 'After eBay fees & shipping', (d.total_profit||0) >= 0 ? 'g' : 'r');
    
    if (d.item_breakdown && d.item_breakdown.length) {
      var bkWrap = EL('div', '', wrap);
      bkWrap.style.cssText = 'margin-top:20px;border-top:1px solid var(--b);padding-top:14px;text-align:left';
      EL('h4', '', bkWrap).textContent = '📦 Individual Item Breakdown';
      for (var k = 0; k < d.item_breakdown.length; k++) {
        var bit = d.item_breakdown[k];
        var itRow = EL('div', 'lr', bkWrap);
        itRow.style.cssText = 'display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--b);font-size:.85rem';
        var leftDiv = EL('div', '', itRow);
        var nmDiv = EL('div', '', leftDiv); nmDiv.style.fontWeight = '600'; nmDiv.textContent = bit.name;
        var subDiv = EL('div', '', leftDiv); subDiv.style.cssText = 'font-size:.72rem;color:var(--t2)'; subDiv.textContent = bit.sold_count + ' recent sold comps';
        var rightDiv = EL('div', '', itRow); rightDiv.style.textAlign = 'right';
        var mVal = EL('div', '', rightDiv); mVal.style.fontWeight = '700'; mVal.textContent = '$' + FMT(bit.market_value);
        var netVal = EL('div', '', rightDiv); netVal.style.cssText = 'font-size:.72rem;color:' + (bit.net >= 0 ? 'var(--g)' : 'var(--r)'); netVal.textContent = 'Est. Net: ' + (bit.net >= 0 ? '+' : '') + '$' + FMT(bit.net);
      }
    }
  } catch(e) { D('lres').innerHTML = '<div class="er on">' + e.message + '</div>'; }
  D('lcalc').textContent = '⚡ Calc';
};

// Deal History
async function loadDh() {
  if (!token) { D('dh').innerHTML = '<div class="empty-state"><h3>👤 Login Required</h3><p>Log in to view your scan history and evaluated flips.</p><button class="bt bt-p" onclick="SHOW(\'authOv\')">Log In / Sign Up</button></div>'; return; }
  try {
    var items = await fetch('/api/deal-history?token=' + getToken()).then(function(r) { return r.json(); });
    if (!items || !items.length) { D('dh').innerHTML = '<div class="empty-state"><h3>⚡ No Scan History Yet</h3><p>Use Quick Scan or Barcode Scanner to evaluate flipping deals.</p><button class="bt bt-p" onclick="showPage(\'quick\')">⚡ Try Quick Scan</button></div>'; return; }
    D('dh').innerHTML = '';
    for (var i = 0; i < items.length; i++) {
      var it = items[i];
      var row = EL('div', 'lr', D('dh'));
      EL('span', '', row).textContent = it.verdict === 'BUY' ? '🔥' : '🚫';
      var tit = EL('span', 'it', row); TXT(tit, it.item_name || '');
      var ip = EL('span', 'ip', row); TXT(ip, '$' + FMT(it.your_price) + ' → $' + FMT(it.market_median));
      var net = EL('span', '', row);
      net.style.cssText = 'color:' + ((it.net_profit||0) >= 0 ? 'var(--g)' : 'var(--r)') + ';font-weight:700';
      TXT(net, ((it.net_profit||0) >= 0 ? '+' : '') + '$' + FMT(it.net_profit));
    }
  } catch(e) { D('dh').innerHTML = '<div style="text-align:center;padding:30px;color:var(--t2)">Could not load.</div>'; }
}

// Trending
async function loadTr() {
  try {
    var items = await fetch('/api/trending').then(function(r) { return r.json(); });
    if (!items || !items.length) { D('tr').innerHTML = '<div class="empty-state"><h3>📈 No Trending Data Yet</h3><p>Trending market searches will appear here as users search.</p></div>'; return; }
    D('tr').innerHTML = '';
    for (var i = 0; i < items.length; i++) {
      var it = items[i];
      var row = EL('div', 'lr', D('tr'));
      row.style.cursor = 'pointer';
      row.onclick = (function(q) { return function() { D('q').value = q; showPage('search'); search(); }; })(it.query);
      var num = EL('span', '', row); num.style.cssText = 'font-weight:700;min-width:24px'; TXT(num, '#' + (i + 1));
      var tit = EL('span', 'it', row); tit.style.fontWeight = '600'; TXT(tit, it.query);
      var cnt = EL('span', '', row); cnt.style.cssText = 'font-size:.68rem;color:var(--t2)'; TXT(cnt, it.count + ' watchers');
    }
  } catch(e) { D('tr').innerHTML = '<div style="text-align:center;padding:30px;color:var(--t2)">Could not load.</div>'; }
}

// Bulk Import
D('bulkGo').onclick = async function() {
  var txt = D('bulkText').value.trim();
  if (!txt) return;
  var lines = txt.split('\n');
  var items = [];
  for (var i = 0; i < lines.length; i++) {
    var line = lines[i].trim();
    if (!line) continue;
    var parts = line.split(',');
    var name = parts[0].trim();
    var price = 0;
    if (parts[1]) { var pm = parts[1].trim().replace('$','').replace(' ',''); price = parseFloat(pm) || 0; }
    if (name && price > 0) items.push({name:name, price:price});
  }
  if (!items.length) { D('bulkRes').innerHTML = '<div class="er on">No valid items found. Use format: Item Name, $Price</div>'; return; }
  D('bulkGo').textContent = 'Processing ' + items.length + ' items...';
  var st = D('bulkSt').value || 'none';
  try {
    var r = await fetch('/api/bulk-price', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({items:items, store_tier:st})});
    var d = await r.json();
    if (!r.ok) throw new Error(d.error || 'Failed');
    var h = '<div class="gd" style="margin-top:12px"><div class="sc"><div class="lb">Total Cost</div><div class="vl">$' + FMT(d.total_cost) + '</div></div><div class="sc"><div class="lb">Total Profit</div><div class="vl ' + (d.total_profit >= 0 ? 'g' : 'r') + '">' + (d.total_profit >= 0 ? '+' : '') + '$' + FMT(d.total_profit) + '</div></div><div class="sc"><div class="lb">Items</div><div class="vl">' + d.total_items + '</div></div></div>';
    if (d.results) {
      h += '<div style="margin-top:10px">';
      for (var i = 0; i < d.results.length; i++) {
        var it = d.results[i];
        h += '<div class="lr"><span class="it" style="font-weight:600">' + esc(it.name) + '</span><span class="ip">$' + FMT(it.cost) + ' → $' + FMT(it.market_median) + '</span><span style="color:' + (it.net_profit >= 0 ? 'var(--g)' : 'var(--r)') + ';font-weight:700">' + (it.net_profit >= 0 ? '+' : '') + '$' + FMT(it.net_profit) + '</span><span style="font-size:.7rem">' + (it.verdict === 'BUY' ? '🔥' : '🚫') + '</span></div>';
      }
      h += '</div>';
    }
    D('bulkRes').innerHTML = h;
  } catch(e) { D('bulkRes').innerHTML = '<div class="er on">' + e.message + '</div>'; }
  D('bulkGo').textContent = '⚡ Price All';
};
function esc(s) { var d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }

// Dashboard
async function loadDash() {
  if (!token) { D('dashStats').innerHTML = '<div style="text-align:center;padding:30px;color:var(--t2)">Login first.</div>'; return; }
  try {
    var r = await fetch('/api/dashboard?token=' + getToken());
    var d = await r.json();
    if (!r.ok) throw new Error(d.error || 'Failed');
    D('dashStats').innerHTML = '<div class="sc"><div class="lb">Total Deals</div><div class="vl">' + d.total_deals + '</div><div class="sm">$' + FMT(d.total_invested) + ' invested</div></div><div class="sc"><div class="lb">Net Profit</div><div class="vl ' + (d.total_net_profit >= 0 ? 'g' : 'r') + '">' + (d.total_net_profit >= 0 ? '+' : '') + '$' + FMT(d.total_net_profit) + '</div><div class="sm">' + d.total_roi + '% ROI</div></div><div class="sc"><div class="lb">Avg Score</div><div class="vl">' + FMT(d.avg_flip_score) + '/100</div></div><div class="sc"><div class="lb">Inventory</div><div class="vl">' + (d.inventory.total_items || 0) + '</div><div class="sm">$' + FMT(d.inventory.sold_profit || 0) + ' sold profit</div></div>';
    if (d.categories && Object.keys(d.categories).length) {
      D('dashCats').innerHTML = '<h3 style="margin-top:14px">📂 By Category</h3><div class="gd">' + Object.keys(d.categories).map(function(c) { return '<div class="sc"><div class="lb">' + c + '</div><div class="vl">' + d.categories[c] + '</div></div>'; }).join('') + '</div>';
    }
  } catch(e) { D('dashStats').innerHTML = '<div style="text-align:center;padding:30px;color:var(--t2)">Could not load.</div>'; }
}
D('dashRef').onclick = loadDash;

// What's Hot
// ═══ PROMOTED OPTIMIZER ═══
D('poGo').onclick = async function() {
  var q = D('poq').value.trim();
  var bp = parseFloat(D('pobp').value) || 0;
  var st = D('post').value || 'none';
  var sh = parseFloat(D('poship').value) || 0;
  if (!q || bp <= 0) return;
  D('poGo').textContent = 'Optimizing...';
  try {
    var r = await fetch('/api/promoted-optimize?q=' + encodeURIComponent(q) + '&buy_price=' + bp.toFixed(2) + '&store_tier=' + st + '&shipping=' + sh.toFixed(2));
    var d = await r.json();
    if (!r.ok) throw new Error(d.error || 'Failed');
    var rec = d.recommendation || {};
    var res = D('poRes');
    res.innerHTML = '';
    var wrap = EL('div', 'cd', res);
    wrap.style.cssText = 'border:2px solid var(--a);background:rgba(91,141,239,.08)';
    var big = EL('div', '', wrap);
    big.style.cssText = 'font-size:1.6rem;font-weight:800;color:var(--a);margin-bottom:8px';
    TXT(big, '\ud83d\udce2 Use ' + rec.rate + '% Ad Rate');
    var reason = EL('div', '', wrap);
    reason.style.cssText = 'font-size:.85rem;color:var(--t2);margin-bottom:12px';
    TXT(reason, rec.reason || '');
    var grid = EL('div', 'gd', wrap);
    addStatCard(grid, '💰 Market Median', '$' + FMT(d.market_median), '', '');
    addStatCard(grid, '💵 Net Profit', (rec.net_profit >= 0 ? '+' : '') + '$' + FMT(rec.net_profit), rec.net_margin + '%', rec.net_profit >= 0 ? 'g' : 'r');
    addStatCard(grid, '⏱ Sells In', '~' + rec.days_to_sell_estimate + 'd', 'Velocity ' + rec.velocity_multiplier + 'x', '');
    addStatCard(grid, '📈 Expected Daily', (rec.expected_daily_profit >= 0 ? '+' : '') + '$' + FMT(rec.expected_daily_profit), '/day', rec.expected_daily_profit >= 0 ? 'g' : 'r');
    var tbl = EL('div', '', res);
    tbl.style.cssText = 'margin-top:16px;overflow-x:auto';
    var table = EL('table', '', tbl);
    table.style.cssText = 'width:100%;border-collapse:collapse;font-size:.78rem';
    var thead = EL('thead', '', table);
    thead.innerHTML = '<tr style="border-bottom:1px solid var(--b)"><th style="text-align:left;padding:6px">Ad Rate</th><th style="text-align:right;padding:6px">Net Profit</th><th style="text-align:right;padding:6px">Ad Cost</th><th style="text-align:right;padding:6px">~Days to Sell</th><th style="text-align:right;padding:6px">Expected Daily</th></tr>';
    var tbody = EL('tbody', '', table);
    for (var i = 0; i < d.scenarios.length; i++) {
      var s = d.scenarios[i];
      var row = EL('tr', '', tbody);
      row.style.cssText = 'border-bottom:1px solid var(--b)';
      if (s.rate === rec.rate) row.style.background = 'rgba(91,141,239,.15)';
      row.innerHTML = '<td style="padding:6px">' + s.rate + '%' + (s.rate === rec.rate ? ' ⭐' : '') + '</td><td style="text-align:right;padding:6px;color:' + (s.net_profit >= 0 ? 'var(--g)' : 'var(--r)') + '">' + (s.net_profit >= 0 ? '+' : '') + '$' + FMT(s.net_profit) + '</td><td style="text-align:right;padding:6px">$' + FMT(s.promoted_fee) + '</td><td style="text-align:right;padding:6px">' + s.days_to_sell_estimate + 'd</td><td style="text-align:right;padding:6px;color:' + (s.expected_daily_profit >= 0 ? 'var(--g)' : 'var(--r)') + '">' + (s.expected_daily_profit >= 0 ? '+' : '') + '$' + FMT(s.expected_daily_profit) + '</td>';
    }
  } catch(e) { D('poRes').innerHTML = '<div class="er on">' + e.message + '</div>'; }
  D('poGo').textContent = 'Optimize';
};
D('poq').onkeydown = D('pobp').onkeydown = function(e) { if (e.key === 'Enter') D('poGo').click(); };

// ═══ EBAY SELLER DASHBOARD ═══
async function loadSellerDashboard() {
  if (!token) {
    D('sellerStatus').innerHTML = '<span style="color:var(--r)">Login first to connect your eBay seller account.</span>';
    D('sellerConnect').style.display = 'inline-block';
    D('sellerDisconnect').style.display = 'none';
    D('sellerRefresh').style.display = 'none';
    return;
  }
  try {
    var r = await fetch('/api/ebay/status?token=' + getToken());
    var d = await r.json();
    if (!r.ok) throw new Error(d.error || 'Failed');
    if (d.connected) {
      D('sellerStatus').innerHTML = '<span style="color:var(--g)">✅ Connected to eBay seller account</span>' + (d.expires_at ? ' <span style="color:var(--t2)">(token valid)</span>' : '');
      D('sellerConnect').style.display = 'none';
      D('sellerDisconnect').style.display = 'inline-block';
      D('sellerRefresh').style.display = 'inline-block';
      fetchSellerData();
    } else {
      D('sellerStatus').innerHTML = '<span style="color:var(--am)">⚠️ eBay seller account not connected.</span>';
      D('sellerConnect').style.display = 'inline-block';
      D('sellerDisconnect').style.display = 'none';
      D('sellerRefresh').style.display = 'none';
      D('sellerStats').innerHTML = '';
      D('sellerInv').innerHTML = '';
      D('sellerSold').innerHTML = '';
    }
  } catch(err) { D('sellerStatus').innerHTML = '<span style="color:var(--r)">Error: ' + err.message + '</span>'; }
}
async function fetchSellerData() {
  try {
    var dash = await fetch('/api/ebay/dashboard?token=' + getToken()).then(function(r) { return r.json(); });
    D('sellerStats').innerHTML = '';
    addStatCard(D('sellerStats'), '📦 Inventory', String(dash.inventory_count || 0), 'Active items', '');
    addStatCard(D('sellerStats'), '💰 Sold', String(dash.sold_count || 0), '$' + FMT(dash.sold_revenue || 0) + ' revenue', '');
    var inv = await fetch('/api/ebay/inventory?token=' + getToken()).then(function(r) { return r.json(); });
    D('sellerInv').innerHTML = '<h3 style="margin-top:16px">📦 Inventory</h3>';
    if (inv.items && inv.items.length) {
      for (var i = 0; i < inv.items.length; i++) {
        var it = inv.items[i];
        var row = EL('div', 'lr', D('sellerInv'));
        EL('span', 'it', row).textContent = it.title || 'Untitled';
        EL('span', 'ip', row).textContent = '$' + FMT(it.price);
      }
    } else { D('sellerInv').innerHTML += '<div style="text-align:center;padding:20px;color:var(--t2)">No inventory items found.</div>'; }
    var sold = await fetch('/api/ebay/sold?token=' + getToken()).then(function(r) { return r.json(); });
    D('sellerSold').innerHTML = '<h3 style="margin-top:16px">💰 Sold Orders</h3>';
    if (sold.orders && sold.orders.length) {
      for (var i = 0; i < sold.orders.length; i++) {
        var it = sold.orders[i];
        var row = EL('div', 'lr', D('sellerSold'));
        EL('span', 'it', row).textContent = it.title || 'Untitled';
        EL('span', 'ip', row).textContent = '$' + FMT(it.price);
        EL('span', 'id', row).textContent = it.sold_date ? it.sold_date.split('T')[0] : '';
      }
    } else { D('sellerSold').innerHTML += '<div style="text-align:center;padding:20px;color:var(--t2)">No sold orders found.</div>'; }
  } catch(e) { D('sellerStatus').innerHTML = '<span style="color:var(--r)">Error loading seller data: ' + e.message + '</span>'; }
}
D('sellerConnect').onclick = function() {
  if (!token) { alert('Login first.'); return; }
  fetch('/api/ebay/auth?token=' + getToken())
    .then(function(r) { return r.json(); })
    .then(function(d) { if (d.auth_url) window.open(d.auth_url, '_blank'); else alert(d.error); })
    .catch(function(e) { alert('Error: ' + e.message); });
};
D('sellerDisconnect').onclick = async function() {
  await fetch('/api/ebay/disconnect?token=' + getToken(), {method:'POST'});
  loadSellerDashboard();
};
D('sellerRefresh').onclick = fetchSellerData;

// ═══ TITLE OPTIMIZER ═══
D('toGo').onclick = async function() {
  var q = D('toq').value.trim();
  var cond = D('tocond').value || 'all';
  var cur = D('tocur').value.trim();
  if (!q) return;
  D('toGo').textContent = 'Optimizing...';
  try {
    var u = '/api/title-optimize?q=' + encodeURIComponent(q) + '&condition=' + cond;
    if (cur) u += '&current_title=' + encodeURIComponent(cur);
    var r = await fetch(u);
    var d = await r.json();
    if (!r.ok) throw new Error(d.error || 'Failed');
    var res = D('toRes');
    res.innerHTML = '';
    var wrap = EL('div', 'cd', res);
    wrap.style.cssText = 'border:2px solid var(--a);background:rgba(91,141,239,.08)';
    var big = EL('div', '', wrap);
    big.style.cssText = 'font-size:1.1rem;font-weight:700;color:var(--a);margin-bottom:8px';
    TXT(big, '✨ Suggested Title');
    var titleBox = EL('div', '', wrap);
    titleBox.style.cssText = 'font-size:1.05rem;padding:12px;background:var(--bg);border-radius:var(--rs);border:1px solid var(--b);margin-bottom:12px;word-break:break-word';
    titleBox.textContent = d.suggested_title;
    var copyBtn = EL('button', 'bt bt-p', wrap);
    TXT(copyBtn, '📋 Copy Title');
    copyBtn.onclick = function() { navigator.clipboard.writeText(d.suggested_title); copyBtn.textContent = 'Copied!'; setTimeout(function(){ copyBtn.textContent = '📋 Copy Title'; }, 1500); };
    var grid = EL('div', 'gd', wrap);
    grid.style.marginTop = '12px';
    addStatCard(grid, '📊 Suggested Score', d.suggested_score + '/100', 'Higher is better', d.suggested_score >= 70 ? 'g' : (d.suggested_score >= 40 ? 'am' : 'r'));
    if (d.current_title) {
      addStatCard(grid, '📊 Current Score', d.current_score + '/100', 'Your title', d.current_score >= 70 ? 'g' : (d.current_score >= 40 ? 'am' : 'r'));
    }
    addStatCard(grid, '🔑 Top Keywords', Object.keys(d.top_keywords).slice(0, 3).join(', '), Object.keys(d.top_keywords).length + ' found', '');
    if (d.price_insights && d.price_insights.length) {
      var pi = EL('div', 'cd', res);
      EL('h3', '', pi).textContent = '💰 Keywords That Sell for More';
      var piGrid = EL('div', 'gd', pi);
      for (var i = 0; i < Math.min(d.price_insights.length, 4); i++) {
        var kw = d.price_insights[i];
        addStatCard(piGrid, '"' + kw.keyword + '"', '$' + FMT(kw.avg_price), kw.count + ' listings', 'g');
      }
    }
    if (d.top_selling_titles && d.top_selling_titles.length) {
      var top = EL('div', 'cd', res);
      EL('h3', '', top).textContent = '🔥 Top Selling Titles';
      for (var i = 0; i < d.top_selling_titles.length; i++) {
        var t = d.top_selling_titles[i];
        var row = EL('div', 'lr', top);
        row.onclick = (function(u) { return function() { window.open(u, '_blank'); }; })(t.url || '#');
        EL('span', 'it', row).textContent = t.title;
        EL('span', 'ip', row).textContent = '$' + FMT(t.price);
      }
    }
  } catch(e) { D('toRes').innerHTML = '<div class="er on">' + e.message + '</div>'; }
  D('toGo').textContent = 'Optimize';
};
D('toq').onkeydown = D('tocur').onkeydown = function(e) { if (e.key === 'Enter') D('toGo').click(); };

// ═══ SALES ANALYTICS ═══
D('anGo').onclick = loadSalesAnalytics;
D('anInv').onclick = loadInventoryProfit;
async function loadSalesAnalytics() {
  if (!token) { D('anRes').innerHTML = '<div class="er on">Login first.</div>'; return; }
  D('anGo').textContent = 'Loading...';
  var st = D('anSt').value || 'none';
  var start = D('anStart').value || '';
  var end = D('anEnd').value || '';
  var u = '/api/analytics/sales?token=' + getToken() + '&store_tier=' + st;
  if (start) u += '&start_date=' + start;
  if (end) u += '&end_date=' + end;
  try {
    var r = await fetch(u);
    var d = await r.json();
    if (!r.ok) throw new Error(d.error || 'Failed');
    var res = D('anRes');
    res.innerHTML = '';
    var s = d.summary;
    var sum = EL('div', 'gd', res);
    addStatCard(sum, '💰 Revenue', '$' + FMT(s.total_revenue), s.items_sold + ' sold', '');
    addStatCard(sum, '💸 Cost', '$' + FMT(s.total_cost), s.matched_items + ' tracked', '');
    addStatCard(sum, '🧾 Fees', '$' + FMT(s.total_fees), 'eBay fees', '');
    var pcls = s.total_profit >= 0 ? 'g' : 'r';
    addStatCard(sum, '💵 Profit', (s.total_profit >= 0 ? '+' : '') + '$' + FMT(s.total_profit), s.margin_pct + '% margin', pcls);
    addStatCard(sum, '❓ Unmatched', String(s.unmatched_items), 'Need buy price in inventory', s.unmatched_items > 0 ? 'am' : '');
    if (d.matched && d.matched.length) {
      var mt = EL('div', 'cd', res);
      EL('h3', '', mt).textContent = '💰 Matched Sales';
      for (var i = 0; i < d.matched.length; i++) {
        var it = d.matched[i];
        var row = EL('div', 'lr', mt);
        EL('span', 'it', row).textContent = it.title;
        EL('span', 'ic', row).textContent = it.sold_date;
        EL('span', 'ip', row).textContent = '$' + it.sold_price.toFixed(2);
        var prof = EL('span', '', row);
        prof.style.cssText = 'color:' + (it.profit >= 0 ? 'var(--g)' : 'var(--r)') + ';font-weight:700;font-size:.8rem';
        prof.textContent = (it.profit >= 0 ? '+' : '') + '$' + it.profit.toFixed(2);
      }
    }
    if (d.unmatched && d.unmatched.length) {
      var ut = EL('div', 'cd', res);
      EL('h3', '', ut).textContent = '❓ Unmatched Sales (Add to Inventory)';
      for (var i = 0; i < d.unmatched.length; i++) {
        var it = d.unmatched[i];
        var row = EL('div', 'lr', ut);
        EL('span', 'it', row).textContent = it.title;
        EL('span', 'ic', row).textContent = it.sold_date;
        EL('span', 'ip', row).textContent = '$' + it.sold_price.toFixed(2);
      }
    }
    if (d.sales_by_month && d.sales_by_month.length > 1) {
      buildAnalyticsChart(d.sales_by_month);
    } else {
      D('anChartWrap').innerHTML = '';
    }
  } catch(e) {
    D('anRes').innerHTML = '<div class="er on">' + e.message + '</div>';
    D('anChartWrap').innerHTML = '';
  }
  D('anGo').textContent = 'Analyze Sales';
}
async function loadInventoryProfit() {
  if (!token) { D('anRes').innerHTML = '<div class="er on">Login first.</div>'; return; }
  D('anInv').textContent = 'Loading...';
  var st = D('anSt').value || 'none';
  try {
    var r = await fetch('/api/analytics/inventory-profit?token=' + getToken() + '&store_tier=' + st);
    var d = await r.json();
    if (!r.ok) throw new Error(d.error || 'Failed');
    var res = D('anRes');
    res.innerHTML = '<h3 style="margin-bottom:10px">📦 Inventory Profit Potential</h3>';
    if (!d.items || !d.items.length) { res.innerHTML += '<div style="color:var(--t2)">No inventory items with buy price found.</div>'; return; }
    for (var i = 0; i < d.items.length; i++) {
      var it = d.items[i];
      var row = EL('div', 'lr', res);
      EL('span', 'it', row).textContent = it.item_name;
      EL('span', 'ip', row).textContent = '$' + FMT(it.buy_price) + ' \u2192 $' + FMT(it.market_median);
      var prof = EL('span', '', row);
      prof.style.cssText = 'color:' + (it.net_profit >= 0 ? 'var(--g)' : 'var(--r)') + ';font-weight:700;font-size:.8rem';
      prof.textContent = (it.net_profit >= 0 ? '+' : '') + '$' + FMT(it.net_profit);
    }
    D('anChartWrap').innerHTML = '';
  } catch(e) { D('anRes').innerHTML = '<div class="er on">' + e.message + '</div>'; }
  D('anInv').textContent = 'Inventory Profit';
}
function buildAnalyticsChart(months) {
  var wrap = D('anChartWrap');
  wrap.innerHTML = '<div class="cd"><h3>📈 Profit by Month</h3><div class="cw" style="height:220px"><canvas id="anChart"></canvas></div></div>';
  var canvas = D('anChart');
  var labels = months.map(function(m) { return m.month; });
  var data = months.map(function(m) { return m.profit; });
  var color = data.map(function(v) { return v >= 0 ? 'rgba(52,211,153,.8)' : 'rgba(248,113,113,.8)'; });
  new Chart(canvas.getContext('2d'), {
    type: 'bar',
    data: { labels: labels, datasets: [{ label: 'Profit', data: data, backgroundColor: color, borderRadius: 4 }] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { ticks: { color: '#888', callback: function(v){ return '$'+v; } } }, x: { ticks: { color: '#888' } } } }
  });
}

async function loadHot() {
  try {
    var items = await fetch('/api/whats-hot').then(function(r) { return r.json(); });
    if (!items || !items.length) { D('hotFeed').innerHTML = '<div style="text-align:center;padding:30px;color:var(--t2)">No hot items yet.</div>'; return; }
    D('hotFeed').innerHTML = '';
    for (var i = 0; i < items.length; i++) {
      var it = items[i];
      var vIcon = it.volume_trend === 'accelerating' ? '📈' : (it.volume_trend === 'slowing' ? '📉' : '→');
      var row = EL('div', 'lr', D('hotFeed'));
      row.style.cursor = 'pointer';
      row.setAttribute('data-q', it.query);
      row.onclick = (function(q) { return function() { D('q').value = q; showPage('search'); search(); }; })(it.query);
      EL('span', '', row).textContent = '🔥';
      var tit = EL('span', 'it', row); tit.style.fontWeight = '600'; TXT(tit, it.query);
      var ip = EL('span', 'ip', row); TXT(ip, '$' + FMT(it.market_median));
      var meta = EL('span', '', row); meta.style.cssText = 'font-size:.7rem;color:var(--t2)'; TXT(meta, vIcon + ' ' + it.watchers + ' watching');
      var score = EL('span', '', row); score.style.cssText = 'color:' + (it.flip_score >= 70 ? 'var(--g)' : (it.flip_score >= 50 ? 'var(--am)' : 'var(--r)')) + ';font-weight:700;font-size:.8rem'; TXT(score, it.flip_score + '/100');
    }
  } catch(e) { D('hotFeed').innerHTML = '<div style="text-align:center;padding:30px;color:var(--t2)">Could not load.</div>'; }
}

// True ROI
D('roiCalc').onclick = async function() {
  var b = {
    buy_price: parseFloat(D('roiBuy').value) || 0,
    sell_price: parseFloat(D('roiSell').value) || 0,
    category: D('roiCat').value || 'default',
    store_tier: D('roiSt').value || 'none',
    shipping_materials: parseFloat(D('roiShip').value) || 0,
    gas: parseFloat(D('roiGas').value) || 0,
    storage: parseFloat(D('roiStorage').value) || 0,
    hours_spent: parseFloat(D('roiHrs').value) || 0,
    hourly_rate: parseFloat(D('roiRate').value) || 35,
    tax_rate: parseFloat(D('roiTax').value) || 25
  };
  if (!b.buy_price || !b.sell_price) return;
  try {
    var r = await fetch('/api/true-roi', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(b)});
    var d = await r.json();
    if (!r.ok) throw new Error(d.error || 'Failed');
    D('roiRes').innerHTML = '<div class="cd" style="margin-top:12px"><h3>' + (d.final_net >= 0 ? '✅ ' + d.verdict : '❌ ' + d.verdict) + '</h3><div class="gd"><div class="sc"><div class="lb">Net After Fees</div><div class="vl ' + (d.net_after_fees >= 0 ? 'g' : 'r') + '">' + (d.net_after_fees >= 0 ? '+' : '') + '$' + FMT(d.net_after_fees) + '</div></div><div class="sc"><div class="lb">Hidden Costs</div><div class="vl r">-$' + FMT(d.hidden_costs) + '</div><div class="sm">Gas/Storage/Time</div></div><div class="sc"><div class="lb">Taxes</div><div class="vl r">-$' + FMT(d.tax_amount) + '</div></div><div class="sc"><div class="lb">TRUE NET</div><div class="vl ' + (d.final_net >= 0 ? 'g' : 'r') + '" style="font-size:1.5rem">' + (d.final_net >= 0 ? '+' : '') + '$' + FMT(d.final_net) + '</div><div class="sm">' + d.final_margin + '% real margin</div></div></div></div>';
  } catch(e) { D('roiRes').innerHTML = '<div class="er on">' + e.message + '</div>'; }
};

// Photo Upload
var activePhotoTarget = 'main';
var selectedPhotoFiles = [];

function openPhotoModal(target) {
  activePhotoTarget = target || 'main';
  selectedPhotoFiles = [];
  var container = D('photoThumbnails');
  if (container) container.innerHTML = '';
  if (D('photoContext')) D('photoContext').value = '';
  if (D('photoDesc')) D('photoDesc').value = '';
  if (D('photoMarketSeg')) {
    var baseSeg = 'auto';
    if (activePhotoTarget === 'quick' && D('qdSeg')) baseSeg = D('qdSeg').value || 'auto';
    else if (D('marketSeg')) baseSeg = D('marketSeg').value || 'auto';
    D('photoMarketSeg').value = baseSeg;
  }
  if (D('photoResWrap')) D('photoResWrap').style.display = 'none';
  if (D('photoInitialClose')) D('photoInitialClose').style.display = 'block';
  if (D('photoAnalyzeBtn')) {
    D('photoAnalyzeBtn').disabled = false;
    D('photoAnalyzeBtn').textContent = '✨ Analyze with Gemini';
  }
  SHOW('photoOv');
}

function updatePhotoThumbnails() {
  var container = D('photoThumbnails');
  if (!container) return;
  container.innerHTML = '';
  for (var i = 0; i < selectedPhotoFiles.length; i++) {
    (function(idx, file) {
      var wrap = document.createElement('div');
      wrap.style.cssText = 'position:relative;width:60px;height:60px;border-radius:6px;overflow:hidden;background:#000;border:1px solid var(--b);display:inline-block';
      var img = document.createElement('img');
      img.style.cssText = 'width:100%;height:100%;object-fit:cover';
      var reader = new FileReader();
      reader.onload = function(e) { img.src = e.target.result; };
      reader.readAsDataURL(file);
      wrap.appendChild(img);

      var del = document.createElement('button');
      del.innerHTML = '✕';
      del.style.cssText = 'position:absolute;top:2px;right:2px;background:rgba(0,0,0,0.7);color:#fff;border:none;border-radius:50%;width:18px;height:18px;font-size:10px;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0';
      del.onclick = function(e) {
        e.stopPropagation();
        selectedPhotoFiles.splice(idx, 1);
        updatePhotoThumbnails();
      };
      wrap.appendChild(del);
      container.appendChild(wrap);
    })(i, selectedPhotoFiles[i]);
  }
}

if (D('camBtn')) D('camBtn').onclick = function() { openPhotoModal('main'); };

if (D('modalCamBtn')) {
  D('modalCamBtn').onclick = function() { if (D('photoCamInput')) D('photoCamInput').click(); };
}
if (D('modalRollBtn')) {
  D('modalRollBtn').onclick = function() { if (D('photoRollInput')) D('photoRollInput').click(); };
}

if (D('photoCamInput')) {
  D('photoCamInput').onchange = function() {
    if (this.files && this.files[0]) {
      selectedPhotoFiles.push(this.files[0]);
      updatePhotoThumbnails();
    }
    this.value = '';
  };
}
if (D('photoRollInput')) {
  D('photoRollInput').onchange = function() {
    if (this.files) {
      for (var i = 0; i < this.files.length; i++) {
        selectedPhotoFiles.push(this.files[i]);
      }
      updatePhotoThumbnails();
    }
    this.value = '';
  };
}

function compressImage(file, maxDim, quality) {
  return new Promise(function(resolve) {
    if (!file || !file.type.match(/image.*/)) return resolve(file);
    var reader = new FileReader();
    reader.onload = function(readerEvent) {
      var img = new Image();
      img.onload = function() {
        var w = img.width, h = img.height;
        if (w > maxDim || h > maxDim) {
          if (w > h) { h = Math.round(h * (maxDim / w)); w = maxDim; }
          else { w = Math.round(w * (maxDim / h)); h = maxDim; }
        }
        var canvas = document.createElement('canvas');
        canvas.width = w; canvas.height = h;
        var ctx = canvas.getContext('2d');
        ctx.drawImage(img, 0, 0, w, h);
        canvas.toBlob(function(blob) {
          resolve(new File([blob], file.name || 'photo.jpg', {type: 'image/jpeg', lastModified: Date.now()}));
        }, 'image/jpeg', quality || 0.82);
      };
      img.onerror = function() { resolve(file); };
      img.src = readerEvent.target.result;
    };
    reader.onerror = function() { resolve(file); };
    reader.readAsDataURL(file);
  });
}

function analyzePhotoWithContext() {
  if (!selectedPhotoFiles.length) {
    alert('Please add at least one photo first!');
    return;
  }
  D('photoAnalyzeBtn').disabled = true;
  D('photoAnalyzeBtn').textContent = '🔄 Processing...';
  if (D('photoDesc')) {
    D('photoDesc').value = '🔄 Compressing & analyzing...';
    D('photoDesc').disabled = true;
  }
  Promise.all(selectedPhotoFiles.map(function(f) { return compressImage(f, 1200, 0.82); })).then(function(compressedFiles) {
    var fd = new FormData();
    for (var i = 0; i < compressedFiles.length; i++) {
      fd.append('images', compressedFiles[i]);
    }
    fd.append('context', D('photoContext').value.trim());
    fetch('/api/identify', {method:'POST', body:fd})
      .then(function(r){ return r.json(); })
      .then(function(d){
        if (D('photoDesc')) D('photoDesc').disabled = false;
        D('photoAnalyzeBtn').disabled = false;
        D('photoAnalyzeBtn').textContent = '✨ Re-scan';
        if (d.error) {
          if (D('photoDesc')) D('photoDesc').value = '❌ AI Analysis Failed';
          D('aiErrorText').textContent = d.error;
          SHOW('aiErrorOv');
          lastPhotoEstimate = null;
        } else if (d.description) {
          if (D('photoResWrap')) D('photoResWrap').style.display = 'block';
          if (D('photoInitialClose')) D('photoInitialClose').style.display = 'none';
          if (D('photoDesc')) D('photoDesc').value = d.description;
          lastPhotoEstimate = null;
          estimateShipping({
            itemName: d.description,
            shipFieldId: 'ship',
            badgeId: null,
            quiet: true,
            onSuccess: function(est) {
              lastPhotoEstimate = { itemName: d.description, estimate: est };
            },
          });
        } else {
          if (D('photoResWrap')) D('photoResWrap').style.display = 'block';
          if (D('photoInitialClose')) D('photoInitialClose').style.display = 'none';
          if (D('photoDesc')) {
            D('photoDesc').value = '';
            D('photoDesc').placeholder = 'Could not detect product. Type item name manually.';
          }
          lastPhotoEstimate = null;
        }
      })
      .catch(function(err){
        if (D('photoDesc')) D('photoDesc').disabled = false;
        D('photoAnalyzeBtn').disabled = false;
        D('photoAnalyzeBtn').textContent = '✨ Re-scan';
        if (D('photoDesc')) D('photoDesc').value = '❌ Network Error';
        D('aiErrorText').textContent = 'Network error: ' + err.message;
        SHOW('aiErrorOv');
        lastPhotoEstimate = null;
      });
  });
}

if (D('photoAnalyzeBtn')) D('photoAnalyzeBtn').onclick = analyzePhotoWithContext;
if (D('photoContext')) D('photoContext').onkeydown = function(e) { if (e.key === 'Enter') analyzePhotoWithContext(); };
if (D('photoCancel')) D('photoCancel').onclick = function() { HIDE('photoOv'); };
if (D('photoOv')) D('photoOv').onclick = function(e) { if (e.target === D('photoOv')) HIDE('photoOv'); };

if (D('photoSearchBtn')) D('photoSearchBtn').onclick = function() {
  var desc = D('photoDesc').value.trim();
  if (!desc || desc === '🔄 Analyzing image(s)...') return;
  var seg = D('photoMarketSeg') ? (D('photoMarketSeg').value || 'auto') : 'auto';
  HIDE('photoOv');
  if (activePhotoTarget === 'lot') {
    D('li').value = desc; D('ladd').onclick();
  } else if (activePhotoTarget === 'quick') {
    D('qd').value = desc;
    if (D('qdSeg')) D('qdSeg').value = seg;
    if (lastPhotoEstimate && lastPhotoEstimate.estimate) {
      D('qds').value = FMT(lastPhotoEstimate.estimate.mid_usd);
      _showShipBadgeResult('qdsEstBadge', desc, lastPhotoEstimate.estimate, { cached: !!lastPhotoEstimate.estimate._cached });
    }
    rqd();
  } else {
    D('q').value = desc;
    if (D('marketSeg')) D('marketSeg').value = seg;
    if (lastPhotoEstimate && lastPhotoEstimate.estimate) {
      D('ship').value = FMT(lastPhotoEstimate.estimate.mid_usd);
      _showShipBadgeResult('shipEstBadge', desc, lastPhotoEstimate.estimate, { cached: !!lastPhotoEstimate.estimate._cached });
    }
    search();
  }
};

// Voice Input
var recognition = null;
if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
  var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  recognition = new SR();
  recognition.continuous = false; recognition.interimResults = true; recognition.lang = 'en-US';
  recognition.onresult = function(e) {
    var t = '';
    for (var i = e.resultIndex; i < e.results.length; i++) t += e.results[i][0].transcript;
    D('qd').value = t;
    if (e.results[0].isFinal) { D('vst').style.display = 'none'; D('micBtn').textContent = '🎤'; D('micBtn').style.background = ''; setTimeout(rqd, 400); }
  };
  recognition.onerror = function() { D('vst').style.display = 'none'; D('micBtn').textContent = '🎤'; D('micBtn').style.background = ''; };
  recognition.onend = function() { D('vst').style.display = 'none'; D('micBtn').textContent = '🎤'; D('micBtn').style.background = ''; };
}
D('micBtn').onclick = function() {
  if (!recognition) { alert('Voice input requires Chrome or Edge.'); return; }
  try {
    recognition.start();
    D('micBtn').textContent = '🔴'; D('micBtn').style.background = 'rgba(248,113,113,.2)';
    if (D('vst')) { D('vst').textContent = '🎤 Listening...'; D('vst').style.display = 'block'; }
  } catch(e) {}
};

// Barcode & Box Scanner
var activeScanTarget = 'quick';
var html5QrCodeScanner = null;

function startScanFor(target) {
  activeScanTarget = target;
  SHOW('scanOv'); D('scanSt').textContent = 'Starting live camera scanner...';
  if (D('scanManualInput')) D('scanManualInput').value = '';
  
  if (window.Html5Qrcode) {
    if (!html5QrCodeScanner) {
      html5QrCodeScanner = new Html5Qrcode("scanVidBox");
    }
    html5QrCodeScanner.start(
      { facingMode: "environment" },
      { fps: 10, qrbox: { width: 250, height: 120 } },
      function(decodedText, decodedResult) {
        D('scanSt').textContent = 'Found: ' + decodedText;
        stopScan(); lookupBarcode(decodedText);
      },
      function(errorMessage) {}
    ).then(function() {
      D('scanSt').textContent = 'Point camera at a UPC or QR code';
    }).catch(function(err) {
      D('scanSt').textContent = 'Live camera restricted. Please use Snap Photo above or type UPC!';
    });
  } else {
    D('scanSt').textContent = 'Scanner library loading. Please use Snap Photo above or type UPC!';
  }
}

if (D('mainScanBtn')) D('mainScanBtn').onclick = function() { startScanFor('main'); };
if (D('scanBtn')) D('scanBtn').onclick = function() { startScanFor('quick'); };
if (D('lotScanBtn')) D('lotScanBtn').onclick = function() { startScanFor('lot'); };

if (D('scanNativeCamBtn')) {
  D('scanNativeCamBtn').onclick = function() {
    stopScan(); openPhotoModal(activeScanTarget);
  };
}
if (D('scanManualBtn')) {
  D('scanManualBtn').onclick = function() {
    var code = D('scanManualInput').value.trim();
    if (!code) return;
    stopScan(); lookupBarcode(code);
  };
}
if (D('scanManualInput')) {
  D('scanManualInput').onkeydown = function(e) { if (e.key === 'Enter') D('scanManualBtn').onclick(); };
}

function stopScan() {
  if (html5QrCodeScanner && html5QrCodeScanner.isScanning) {
    html5QrCodeScanner.stop().catch(function(){});
  }
  HIDE('scanOv');
}

async function lookupBarcode(code) {
  var tit = code;
  try {
    var r = await fetch('/api/barcode?code=' + encodeURIComponent(code));
    var d = await r.json();
    if (d && d.title) {
      tit = d.brand ? d.brand + ' ' + d.title : d.title;
    }
  } catch(e) {}

  if (activeScanTarget === 'lot') {
    D('li').value = tit; D('ladd').onclick();
  } else if (activeScanTarget === 'quick') {
    D('qd').value = tit; setTimeout(rqd, 200);
  } else {
    D('q').value = tit; search();
  }
}

// Wire up the shipping estimator buttons (must run after DOM is ready)
_wireShipEstButtons();

// Service Worker
if ('serviceWorker' in navigator) {
  window.addEventListener('load', function() {
    navigator.serviceWorker.register('/static/sw.js').catch(function(){});
  });
}

