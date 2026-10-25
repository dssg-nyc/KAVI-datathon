// HTML for resource cards (list and map popups). Every data value passes through escapeHtml().
import { serviceColor } from './resources.js';

export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}

// Only http(s) links; a bare "www.example.org" gets https:// in front.
function safeUrl(url) {
  const u = url.trim();
  if (!u) return '';
  if (/^https?:\/\//i.test(u)) return u;
  return /^[\w.-]+\.[a-z]{2,}(\/|$)/i.test(u) ? `https://${u}` : '';
}

// A tel: link only when the field holds exactly one 10- or 11-digit US number.
function phoneHtml(phone) {
  const digits = phone.replace(/\D/g, '');
  const linkable = digits.length === 10 || (digits.length === 11 && digits.startsWith('1'));
  return linkable ? `<a href="tel:+${digits.length === 10 ? '1' : ''}${digits}">${escapeHtml(phone)}</a>` : escapeHtml(phone);
}

function tagsHtml(r) {
  const madeFor = r.madeForPicked ?? [];
  return [
    ...madeFor.map((a) => `<span class="tag who made-for">Made for ${escapeHtml(a)}</span>`),
    ...r.services.map((s) => `<span class="tag"><span class="dot" style="background:${serviceColor(s)}"></span>${escapeHtml(s)}</span>`),
    ...r.audiences.filter((a) => !madeFor.includes(a)).map((a) => `<span class="tag who">${escapeHtml(a)}</span>`),
    r.forEveryone ? '<span class="tag who open">Open to everyone</span>' : '',
    r.spanish ? '<span class="tag lang">Spanish-speaking</span>' : '',
  ].join('');
}

function badgeHtml(r) {
  if (r.distance != null) return `<span class="dist">${r.distance.toFixed(1)} mi</span>`;
  if (!r.inPerson) return `<span class="dist remote">${escapeHtml(r.remoteLabel)}</span>`;
  return '';
}

export function cardHtml(r, { compact = false } = {}) {
  const web = safeUrl(r.website);
  const contact = [
    r.phone ? phoneHtml(r.phone) : '',
    web ? `<a href="${escapeHtml(web)}" target="_blank" rel="noopener">${escapeHtml(r.website.replace(/^https?:\/\//i, '').replace(/\/$/, ''))}</a>` : '',
  ].filter(Boolean).join(' · ');
  const desc = compact && r.description.length > 220 ? `${r.description.slice(0, 220)}…` : r.description;
  return `<div class="card-head"><strong>${escapeHtml(r.name)}</strong>${badgeHtml(r)}</div>
    ${r.address ? `<div class="meta">${escapeHtml(r.address)}</div>` : ''}
    ${contact ? `<div class="meta">${contact}</div>` : ''}
    ${desc ? `<p class="desc">${escapeHtml(desc)}</p>` : ''}
    <div class="tags">${tagsHtml(r)}</div>
    ${!compact && r.inPerson ? '<div class="on-map">Show on map →</div>' : ''}`;
}

export function popupHtml(group) {
  if (group.length === 1) return cardHtml(group[0], { compact: true });
  return `<div class="popup-head">${group.length} places at this address</div>`
    + group.map((r) => `<div class="popup-item">${cardHtml(r, { compact: true })}</div>`).join('');
}
