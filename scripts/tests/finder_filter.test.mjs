// Tests for finder/filter.js and toResource() in finder/resources.js. Run: node --test scripts/tests/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { countBy, matchingResources, newFilters } from '../../finder/filter.js';
import { isListed, toResource } from '../../finder/resources.js';

const rows = [
  { id: 1, organization_name: 'Bronx Legal', row_type: 'mapped', latitude: 40.82, longitude: -73.92, borough: 'Bronx', service_types_all: ['Legal & Rights'], pdf_audiences: ['Youth'], spanish_speaking: true, street: '1 Main St' },
  { id: 2, organization_name: 'Same Building', row_type: 'mapped', latitude: 40.82, longitude: -73.92, borough: 'Bronx', service_types_all: ['Legal & Rights', 'Housing'], pdf_audiences: null, spanish_speaking: null, street: '1 Main St' },
  { id: 3, organization_name: 'Far Legal', row_type: 'mapped', latitude: 40.60, longitude: -74.10, borough: 'Staten Island', service_types_all: ['Legal & Rights'], pdf_audiences: ['Youth'], spanish_speaking: false, street: '9 Far Rd' },
  { id: 4, organization_name: 'Legal Hotline', row_type: 'hotline', latitude: null, longitude: null, borough: null, service_types_all: ['Legal & Rights'], pdf_audiences: ['Youth'], spanish_speaking: true, phone_number: '800-555-0100' },
  { id: 5, organization_name: 'PO Box Org', row_type: 'mailing_address', latitude: null, longitude: null, borough: null, service_types_all: ['Reentry Support'], pdf_audiences: null, street: 'Box 1' },
  { id: 6, organization_name: 'See page 305', row_type: 'cross_reference', description: 'See the full listing on page 305.', service_types_all: ['Reentry Support'] },
];
const resources = rows.filter(isListed).map((row, i) => toResource(row, i));
const near = { label: 'test', lat: 40.83, lon: -73.92 };

test('cross_reference rows are left out; rows without coordinates are phone/online', () => {
  assert.deepEqual(resources.map((r) => r.id), [1, 2, 3, 4, 5]);
  assert.deepEqual(resources.filter((r) => !r.inPerson).map((r) => r.id), [4, 5]);
  assert.equal(resources.find((r) => r.id === 5).remoteLabel, 'By mail or phone');
});

test('distance limits in-person resources but not phone/online ones', () => {
  const f = { ...newFilters(), services: new Set(['Legal & Rights']), place: near, radius: 2 };
  const ids = matchingResources(resources, f).map((r) => r.id);
  assert.deepEqual(ids, [1, 2, 4]);
});

test('audience and Spanish filters use pdf_audiences and spanish_speaking only', () => {
  const f = { ...newFilters(), audiences: new Set(['Youth']), spanish: true };
  assert.deepEqual(matchingResources(resources, f).map((r) => r.id), [1, 4]);
});

test('borough filter skips phone/online resources', () => {
  const f = { ...newFilters(), boroughs: new Set(['Bronx']) };
  assert.deepEqual(matchingResources(resources, f).map((r) => r.id).sort(), [1, 2, 4, 5]);
});

test('counts ignore their own filter', () => {
  const f = { ...newFilters(), services: new Set(['Housing']) };
  const services = countBy(resources, f, 'services');
  assert.equal(services.get('Legal & Rights'), 4);
  assert.equal(services.get('Housing'), 1);
  const how = countBy(resources, { ...newFilters(), how: 'in_person' }, 'how');
  assert.deepEqual([how.get('in_person'), how.get('remote')], [3, 2]);
});
