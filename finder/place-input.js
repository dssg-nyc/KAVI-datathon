// Location box: address/ZIP autocomplete (NYC GeoSearch), "use my location", and a note naming the place in use.
// Typed text becomes a place only when it is resolved: a suggestion is picked, Enter is pressed, or resolve() is called.
import { escapeHtml } from './cards.js';
import { searchPlaces } from './geo.js';

// getPlace() returns the current place; onChange(place or null) is called when it changes.
export function createPlaceInput(el, { resources, getPlace, onChange }) {
  el.innerHTML = `<div class="place">
      <input type="search" placeholder="Address or ZIP" aria-label="Address or ZIP" autocomplete="off"
        role="combobox" aria-autocomplete="list" aria-expanded="false">
      <button type="button" class="me" title="Use my location" aria-label="Use my location">◎</button>
      <ul class="sugg" role="listbox" hidden></ul>
    </div>
    <p class="meta place-note" aria-live="polite"></p>`;
  const input = el.querySelector('input');
  const list = el.querySelector('.sugg');
  const note = el.querySelector('.place-note');
  let suggestions = [];
  let suggestionsFor = '';
  let highlighted = -1;
  let pending = false; // text typed but not resolved to a place yet
  let timer = 0;
  let controller = null;

  const placeNote = () => (getPlace() ? `Searching near: ${getPlace().label}` : '');
  const setNote = (text = pending ? 'Pick an address from the list, or press Enter to use the best match.' : placeNote()) => {
    note.textContent = text;
  };

  function showSuggestions(show) {
    list.hidden = !show || !suggestions.length;
    input.setAttribute('aria-expanded', String(!list.hidden));
  }

  function renderSuggestions() {
    list.innerHTML = suggestions.map((p, i) => `<li role="option" data-i="${i}" aria-selected="${i === highlighted}">${escapeHtml(p.label)}</li>`).join('');
    showSuggestions(true);
  }

  function pick(place) {
    input.value = place.label;
    pending = false;
    showSuggestions(false);
    onChange(place);
    setNote();
  }

  async function fetchSuggestions(text) {
    controller?.abort();
    controller = new AbortController();
    const result = await searchPlaces(text, resources, { signal: controller.signal });
    suggestions = result.places;
    suggestionsFor = text;
    if (result.failed && !result.places.length) setNote('Address search is not working right now. Enter a 5-digit ZIP, use your location, or click the map.');
    return result;
  }

  // Turns typed text into a place using the best match. Returns false when nothing matched.
  async function resolve() {
    const text = input.value.trim();
    if (!pending || !text) return true;
    clearTimeout(timer);
    try {
      if (suggestionsFor !== text) await fetchSuggestions(text);
    } catch (error) {
      if (error.name === 'AbortError') return false;
      throw error;
    }
    const best = suggestions[Math.max(highlighted, 0)];
    if (best) {
      pick(best);
      return true;
    }
    setNote(`No match for “${text}”. Try a street address or a 5-digit ZIP.`);
    return false;
  }

  input.addEventListener('input', () => {
    clearTimeout(timer);
    const text = input.value.trim();
    pending = Boolean(text);
    highlighted = -1;
    if (!text) {
      suggestions = [];
      showSuggestions(false);
      if (getPlace()) onChange(null);
      setNote();
      return;
    }
    setNote();
    timer = setTimeout(async () => {
      try {
        await fetchSuggestions(text);
      } catch (error) {
        if (error.name !== 'AbortError') console.warn(error);
        return;
      }
      if (input.value.trim() === text) renderSuggestions();
    }, 250);
  });

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      resolve();
    } else if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && suggestions.length) {
      e.preventDefault();
      const step = e.key === 'ArrowDown' ? 1 : -1;
      highlighted = (highlighted + step + suggestions.length) % suggestions.length;
      renderSuggestions();
    } else if (e.key === 'Escape') {
      showSuggestions(false);
    }
  });
  input.addEventListener('blur', () => setTimeout(() => showSuggestions(false), 150));

  // mousedown (not click) so the pick happens before the input's blur hides the list.
  list.addEventListener('mousedown', (e) => {
    const li = e.target.closest('li');
    if (!li) return;
    e.preventDefault();
    pick(suggestions[Number(li.dataset.i)]);
  });

  el.querySelector('.me').addEventListener('click', () => {
    if (!navigator.geolocation) {
      setNote('This browser cannot share a location. Type an address or ZIP instead.');
      return;
    }
    setNote('Finding your location…');
    navigator.geolocation.getCurrentPosition(
      (pos) => pick({ lat: pos.coords.latitude, lon: pos.coords.longitude, label: 'your location' }),
      () => setNote('Your browser did not share a location. Type an address or ZIP instead.'),
      { timeout: 10000 },
    );
  });

  // Shows the current place in the box, e.g. after a click on the map.
  function sync() {
    input.value = getPlace()?.label ?? '';
    pending = false;
    showSuggestions(false);
    setNote();
  }
  sync();

  return { sync, resolve, isPending: () => pending };
}
