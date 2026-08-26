/* The live map is the spatial surface for locating and opening sites. */

import * as store from './store.js';
import * as forms from './forms.js';
import { el } from './ui.js';
import { isWithinArizona, loadLeaflet, sitePoint } from './leaflet.js';

export function mapView(ctx) {
  const root = el('div', 'view view-map');
  const note = el('p', 'map-status', 'Loading map…');
  const canvas = el('div', 'live-map');
  root.append(note, canvas);

  loadLeaflet().then((L) => {
    const map = L.map(canvas, {
      maxBounds: [[30.8, -115.2], [37.25, -108.65]], maxBoundsViscosity: 1,
    }).setView([33.45, -112.07], 7);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19, attribution: '&copy; OpenStreetMap contributors',
    }).addTo(map);
    requestAnimationFrame(() => {
      if (canvas.isConnected) map.invalidateSize({ pan: false });
    });
    note.textContent = 'Arizona only. Click the map to create a site, or open a site to edit its boundary.';

    const layers = [];
    for (const site of store.sites()) {
      const point = sitePoint(site);
      if (site.polygon && site.polygon.features) {
        const boundary = L.geoJSON(site.polygon).addTo(map);
        boundary.bindPopup(site.name);
        boundary.on('click', () => ctx.go(`#/site/${site.id}`));
        layers.push(boundary);
      }
      if (point) {
        const marker = L.marker([point.lat, point.lon ?? point.lng]).addTo(map);
        marker.bindPopup(site.name);
        marker.on('click', () => ctx.go(`#/site/${site.id}`));
        layers.push(marker);
      }
    }
    if (layers.length) {
      const group = L.featureGroup(layers);
      map.fitBounds(group.getBounds().pad(0.25), { maxZoom: 11 });
    }
    map.on('click', (event) => {
      if (!isWithinArizona(event.latlng)) {
        note.textContent = 'FortyGuard weather for this workspace is limited to Arizona.';
        return;
      }
      forms.editSite(null, () => ctx.refresh(), event.latlng);
    });
  }).catch(() => {
    note.textContent = 'The map could not load. Check your connection and try again.';
  });

  return root;
}
