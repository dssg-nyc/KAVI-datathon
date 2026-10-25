// Tests for scripts/nypl_connections_to_geojson.ts.
// Run with: node --test scripts/tests/nypl_connections_to_geojson.test.ts
import { describe, test, afterEach } from 'node:test'
import assert from 'node:assert/strict'
import {
  buildBatchCsv,
  cleanZip,
  csvCell,
  geocode,
  geocodeWithGeoSearch,
  houseNumbersMatch,
  isGeocodable,
  mapWithConcurrency,
  parseCsv,
  parseGeocodeResponse,
  pickGeoSearchMatch,
  toFeature,
  BENCHMARK,
  type Record_,
} from '../nypl_connections_to_geojson.ts'

describe('parseCsv', () => {
  // A plain grid with no quoting should split cleanly on commas/newlines.
  test('splits a simple grid', () => {
    assert.deepEqual(parseCsv('a,b,c\n1,2,3\n'), [['a', 'b', 'c'], ['1', '2', '3']])
  })

  // The NYPL CSV has ~39 rows like "C/O Family of Woodstock, Inc." in Address Line 2 —
  // a comma inside a quoted field must not be treated as a column separator.
  test('keeps commas inside quoted fields', () => {
    assert.deepEqual(parseCsv('name,note\nAcme,"C/O Smith, Inc."\n'), [
      ['name', 'note'],
      ['Acme', 'C/O Smith, Inc.'],
    ])
  })

  // RFC4180 escapes a literal quote as two quotes in a row; that should collapse to one.
  test('unescapes doubled quotes inside quoted fields', () => {
    assert.deepEqual(parseCsv('a\n"she said ""hi"""\n'), [['a'], ['she said "hi"']])
  })

  // A quoted field is allowed to contain the row separator itself.
  test('keeps newlines inside quoted fields', () => {
    assert.deepEqual(parseCsv('a,b\n1,"line one\nline two"\n'), [['a', 'b'], ['1', 'line one\nline two']])
  })

  // Trailing/stray blank lines in the source file shouldn't become empty rows.
  test('drops blank lines', () => {
    assert.deepEqual(parseCsv('a,b\n1,2\n\n3,4\n'), [['a', 'b'], ['1', '2'], ['3', '4']])
  })

  // The source file and the Census response may use CRLF rather than LF.
  test('handles CRLF line endings', () => {
    assert.deepEqual(parseCsv('a,b\r\n1,2\r\n'), [['a', 'b'], ['1', '2']])
  })
})

describe('csvCell', () => {
  // Most fields need no escaping at all.
  test('leaves plain values alone', () => {
    assert.equal(csvCell('Kingston'), 'Kingston')
  })

  // A value containing a comma must be wrapped in quotes or it would split into two columns.
  test('quotes values containing commas', () => {
    assert.equal(csvCell('Kingston, NY'), '"Kingston, NY"')
  })

  // A literal quote inside a quoted value must be doubled per RFC4180.
  test('escapes embedded quotes', () => {
    assert.equal(csvCell('12 "Main" St'), '"12 ""Main"" St"')
  })
})

// A full NYPL CSV row with every column blank unless overridden, so each test only has to
// spell out the fields it cares about.
function record(fields: Partial<Record_>): Record_ {
  const base: Record_ = {
    'Organization Name': '', 'Street Number': '', 'Address Line 2': '', Street: '', City: '',
    State: '', 'Zip Code': '', 'Phone Number': '', Website: '', Description: '', Category: '',
    Subcategory: '', 'Spanish-speaking (Y/N)': '', 'Works w/ Currently Incarcerated/Pre-release (Y/N)': '',
    'ATI Program (Y/N)': '', 'Know Your Rights Content (Y/N)': '', Notes: '',
  }
  return { ...base, ...fields }
}

describe('isGeocodable', () => {
  // The Census geocoder needs a street plus either a city or a zip to have a shot at matching.
  test('needs a street plus a city or zip', () => {
    assert.equal(isGeocodable(record({ Street: 'Albany Avenue', City: 'Kingston' })), true)
    assert.equal(isGeocodable(record({ Street: 'Albany Avenue', 'Zip Code': '12401' })), true)
  })

  // A street name alone (no city, no zip) isn't enough to send to the geocoder.
  test('rejects a street with neither city nor zip', () => {
    assert.equal(isGeocodable(record({ Street: 'Albany Avenue' })), false)
  })

  // ~291 rows are hotlines or online-only resources with no address at all; they should
  // never be sent to the geocoder.
  test('rejects a row with no street at all (hotlines, online-only resources)', () => {
    assert.equal(isGeocodable(record({ City: 'Kingston', 'Zip Code': '12401' })), false)
    assert.equal(isGeocodable(record({})), false)
  })
})

describe('cleanZip', () => {
  // Confirmed against the published ArcGIS layer during PR review (review.md): this row's
  // zip is a typo that would otherwise send the wrong zip to both geocoders.
  test('fixes the known Bedford-Stuyvesant Family Health Center zip typo', () => {
    const r = cleanZip(record({
      'Organization Name': 'THE BEDFORD-STUYVESANT FAMILY HEALTH CENTER - 4 (Wellness Center Program)',
      'Zip Code': '12116',
    }))
    assert.equal(r['Zip Code'], '11216')
  })

  // Same, for the second row review.md flagged.
  test('fixes the known Staten Island Justice Center zip typo', () => {
    const r = cleanZip(record({
      'Organization Name': 'CENTER FOR JUSTICE INNOVATION (CJI)—THE STATEN ISLAND JUSTICE CENTER',
      'Zip Code': '10304',
    }))
    assert.equal(r['Zip Code'], '10301')
  })

  // Any row that isn't one of the two known-bad ones must pass through unchanged.
  test('leaves every other row untouched', () => {
    const r = record({ 'Organization Name': 'SOME OTHER ORG', 'Zip Code': '10304' })
    assert.equal(cleanZip(r)['Zip Code'], '10304')
  })
})

describe('buildBatchCsv', () => {
  // Each row must carry the caller's id (so results can be matched back up) and quote any
  // field that itself contains a comma (e.g. "Troy, Rensselaer").
  test('pairs each id with its address row, quoting where needed', () => {
    const csv = buildBatchCsv(
      [5, 9],
      [
        { street: '31 Albany Avenue', city: 'Kingston', state: 'NY', zip: '12401' },
        { street: '1 Main St', city: 'Troy, Rensselaer', state: 'NY', zip: '12180' },
      ],
    )
    assert.equal(csv, '5,31 Albany Avenue,Kingston,NY,12401\n9,1 Main St,"Troy, Rensselaer",NY,12180')
  })
})

describe('parseGeocodeResponse', () => {
  // A "Match" row carries coordinates as a single "lon,lat" column that needs splitting, and
  // the address Census actually matched, kept for provenance.
  test('reads coordinates and the matched address out of a matched row', () => {
    const csv = '"1","350 Fifth Avenue, New York, NY, 10118","Match","Exact","350 5TH AVE, NEW YORK, NY, 10118","-73.985075577551,40.747850846857","59653473","L"'
    const results = parseGeocodeResponse(csv)
    assert.deepEqual(results.get(1), { matched: true, lon: -73.985075577551, lat: 40.747850846857, matchedAddress: '350 5TH AVE, NEW YORK, NY, 10118' })
  })

  // A "No_Match" row (e.g. a PO box like "Box 188") has only 3 columns and no coordinates.
  test('marks a No_Match row as unmatched with no coordinates', () => {
    const results = parseGeocodeResponse('"2","1 Police Plaza, New York, NY, 10038","No_Match"')
    assert.deepEqual(results.get(2), { matched: false })
  })

  // The real response is one row per input address; both outcomes can appear in the same batch.
  test('handles multiple rows', () => {
    const csv = [
      '"1","a","Match","Exact","a","-1,2","id","L"',
      '"2","b","No_Match"',
    ].join('\n')
    const results = parseGeocodeResponse(csv)
    assert.equal(results.size, 2)
    assert.equal(results.get(1)?.matched, true)
    assert.equal(results.get(2)?.matched, false)
  })
})

describe('toFeature', () => {
  // When every address column is present and the geocoder matched, the feature should carry
  // the full set of OSM addr:* tags, a Point geometry, and the geocoder that resolved it.
  test('builds addr:* tags from the present address columns', () => {
    const f = toFeature(
      record({ 'Street Number': '31', Street: 'Albany Avenue', City: 'Kingston', State: 'NY', 'Zip Code': '12401' }),
      { matched: true, lon: -74.0, lat: 41.9, source: 'census' },
    )
    assert.equal(f.properties['addr:housenumber'], '31')
    assert.equal(f.properties['addr:street'], 'Albany Avenue')
    assert.equal(f.properties['addr:city'], 'Kingston')
    assert.equal(f.properties['addr:state'], 'NY')
    assert.equal(f.properties['addr:postcode'], '12401')
    assert.equal(f.properties['addr:country'], 'US')
    assert.equal(f.properties.geocode_match, 'matched')
    assert.equal(f.properties.geocode_source, 'census')
    assert.deepEqual(f.geometry, { type: 'Point', coordinates: [-74.0, 41.9] })
  })

  // Every point says which address the geocoder actually placed, and whether it needs review.
  test('carries the matched address and review note', () => {
    const f = toFeature(
      record({ 'Street Number': '45', Street: 'Suffolk Street', City: 'New York', State: 'NY', 'Zip Code': '10002' }),
      { matched: true, lon: -73.98, lat: 40.71, source: 'census', matchedAddress: '45 SUFFOLK ST, NEW YORK, NY, 10002', review: 'Confirm the address.' },
    )
    assert.equal(f.properties.geocode_matched_address, '45 SUFFOLK ST, NEW YORK, NY, 10002')
    assert.equal(f.properties.geocode_review, 'Confirm the address.')
  })

  // A hotline/online-only row (no address columns, never sent to the geocoder) must not
  // gain any addr:* tags, and should be flagged "not_attempted" rather than dropped.
  test('omits addr:* tags entirely for a row with no address fields', () => {
    const f = toFeature(record({}), undefined)
    for (const key of Object.keys(f.properties)) assert.ok(!key.startsWith('addr:'))
    assert.equal(f.properties.geocode_match, 'not_attempted')
    assert.equal(f.properties.geocode_source, '')
    assert.equal(f.geometry, null)
  })

  // A row that had an address but the geocoder couldn't place (e.g. a PO box) keeps its
  // addr:* tags but gets null geometry and is flagged "unmatched", not dropped.
  test('marks an address that failed to geocode as unmatched with null geometry', () => {
    const f = toFeature(record({ Street: 'Box 188', City: 'Yaphank' }), { matched: false })
    assert.equal(f.properties.geocode_match, 'unmatched')
    assert.equal(f.properties.geocode_source, '')
    assert.equal(f.geometry, null)
  })

  // Every original CSV column (Organization Name, Notes, the Y/N flags, etc.) must survive
  // untouched on the feature's properties — this script only adds fields, never removes any.
  test('keeps every original column on properties, unchanged', () => {
    const r = record({ 'Organization Name': 'Acme', Notes: 'see page 12' })
    const f = toFeature(r, undefined)
    assert.equal(f.properties['Organization Name'], 'Acme')
    assert.equal(f.properties['Notes'], 'see page 12')
  })
})

describe('geocode', () => {
  const realFetch = globalThis.fetch
  afterEach(() => { globalThis.fetch = realFetch })

  // Verifies the actual HTTP contract with the Census batch endpoint: POST, the right URL,
  // a multipart body carrying "benchmark" and an "addressFile" blob — and that a successful
  // response gets parsed into the result map.
  test('posts the address batch as multipart form data and parses the response', async () => {
    let seenUrl: string | URL | undefined
    let seenInit: RequestInit | undefined
    globalThis.fetch = (async (url: string | URL, init?: RequestInit) => {
      seenUrl = url
      seenInit = init
      return new Response('"0","a","Match","Exact","a","-73.9,40.7","1","L"')
    }) as typeof fetch

    const results = await geocode([0], [{ street: '1 Main St', city: 'Troy', state: 'NY', zip: '12180' }])

    assert.equal(results.get(0)?.matched, true)
    assert.equal(String(seenUrl), 'https://geocoding.geo.census.gov/geocoder/locations/addressbatch')
    assert.equal(seenInit?.method, 'POST')
    const body = seenInit?.body as FormData
    assert.ok(body instanceof FormData)
    assert.equal(body.get('benchmark'), BENCHMARK)
    assert.ok(body.get('addressFile') instanceof Blob)
  })

  // The Census server answers 429/502/503/504 when it's busy; the script is supposed to
  // back off and retry rather than fail on the first bad response. The real backoff waits
  // real seconds, so stub the timer too or this test would take ~10s.
  test('retries on a busy response and succeeds once the server recovers', async () => {
    const realSetTimeout = globalThis.setTimeout
    globalThis.setTimeout = ((fn: () => void) => { fn(); return 0 }) as typeof setTimeout

    let calls = 0
    globalThis.fetch = (async () => {
      calls++
      if (calls === 1) return new Response('busy', { status: 503 })
      return new Response('"0","a","Match","Exact","a","-73.9,40.7","1","L"')
    }) as typeof fetch

    try {
      const results = await geocode([0], [{ street: '1 Main St', city: 'Troy', state: 'NY', zip: '12180' }])
      assert.equal(calls, 2)
      assert.equal(results.get(0)?.matched, true)
    } finally {
      globalThis.setTimeout = realSetTimeout
    }
  })

  // A non-retryable status (anything other than 429/502/503/504) should fail fast with a
  // useful error instead of being silently swallowed or retried forever.
  test('throws with the status and body when the server returns a non-retryable error', async () => {
    globalThis.fetch = (async () => new Response('bad request', { status: 400 })) as typeof fetch

    await assert.rejects(
      geocode([0], [{ street: '1 Main St', city: 'Troy', state: 'NY', zip: '12180' }]),
      /HTTP 400.*bad request/s,
    )
  })
})

describe('pickGeoSearchMatch', () => {
  // The real, happy-path case: GeoSearch's top result is at the address we asked for.
  test('returns coordinates when a feature\'s postalcode matches the input zip', () => {
    const match = pickGeoSearchMatch(
      [{ geometry: { coordinates: [-74.003463, 40.713036] }, properties: { postalcode: '10007', housenumber: '1', label: '1 CENTER STREET, New York, NY, USA' } }],
      '10007',
      '1',
    )
    assert.deepEqual(match, { lon: -74.003463, lat: 40.713036, houseNumberMatches: true, label: '1 CENTER STREET, New York, NY, USA' })
  })

  // GeoSearch has no concept of "outside NYC": asking it about a Kingston, NY address gets back
  // a Brooklyn street of the same name with a completely different zip (11213 vs 12401) — this
  // is the exact fallback behavior that makes the zip check necessary.
  test('rejects a fallback match whose zip does not match (address outside NYC)', () => {
    const match = pickGeoSearchMatch(
      [{ geometry: { coordinates: [-73.93931, 40.675917] }, properties: { postalcode: '11213' } }],
      '12401',
    )
    assert.equal(match, null)
  })

  // Some rows have a street and city but no zip at all; there's nothing to validate against,
  // so GeoSearch is never trusted for them even if it returns something.
  test('rejects when there is no zip to validate against', () => {
    const match = pickGeoSearchMatch(
      [{ geometry: { coordinates: [-74, 40.7] }, properties: { postalcode: '10007' } }],
      '',
    )
    assert.equal(match, null)
  })

  // A zip+4 on either side shouldn't break the comparison — only the first 5 digits matter.
  test('compares only the first 5 digits of the zip', () => {
    const match = pickGeoSearchMatch(
      [{ geometry: { coordinates: [-74, 40.7] }, properties: { postalcode: '10007-1234', housenumber: '1' } }],
      '10007',
      '1',
    )
    assert.deepEqual(match, { lon: -74, lat: 40.7, houseNumberMatches: true, label: '' })
  })

  test('returns null when nothing in the result set matches', () => {
    assert.equal(pickGeoSearchMatch([], '10007'), null)
  })

  // Inside NYC, GeoSearch's fallback lands on the right street and zip but a different building:
  // "581 Rogers Avenue" came back as 1038 Rogers Avenue, 1.4 km away. The point is still returned
  // so the caller can fall back to it, but flagged as not matching the house number.
  test('flags a same-zip result with a different house number', () => {
    const match = pickGeoSearchMatch(
      [{ geometry: { coordinates: [-73.95, 40.64] }, properties: { postalcode: '11226', housenumber: '1038', label: '1038 ROGERS AVENUE, Brooklyn, NY, USA' } }],
      '11226',
      '581',
    )
    assert.equal(match?.houseNumberMatches, false)
    assert.equal(match?.label, '1038 ROGERS AVENUE, Brooklyn, NY, USA')
  })
})

describe('houseNumbersMatch', () => {
  test('matches identical numbers, including Queens-style hyphenated ones', () => {
    assert.equal(houseNumbersMatch('581', '581'), true)
    assert.equal(houseNumbersMatch('29-76', '29-76'), true)
  })

  test('rejects a different building on the same street', () => {
    assert.equal(houseNumbersMatch('581', '1038'), false)
    assert.equal(houseNumbersMatch('180', '80'), false)
    assert.equal(houseNumbersMatch('16-16', '16-00'), false)
  })

  test('ignores letter suffixes', () => {
    assert.equal(houseNumbersMatch('76-A', '76'), true)
    assert.equal(houseNumbersMatch('150D', '150'), true)
    assert.equal(houseNumbersMatch('201A', '201'), true)
  })

  // The source CSV writes some ranges with an en dash ("3807–3809 Church Avenue").
  test('accepts either end of a range, written with a hyphen or an en dash', () => {
    assert.equal(houseNumbersMatch('400-430', '400'), true)
    assert.equal(houseNumbersMatch('104-106', '106'), true)
    assert.equal(houseNumbersMatch('3807–3809', '3807'), true)
    assert.equal(houseNumbersMatch('3807–3809', '3419'), false)
  })

  test('never matches when either side is blank', () => {
    assert.equal(houseNumbersMatch('', '1'), false)
    assert.equal(houseNumbersMatch('1', ''), false)
  })
})

describe('mapWithConcurrency', () => {
  // Every item must be processed, and results must land at the same index as their input
  // regardless of how fast each one resolves.
  test('returns results in input order', async () => {
    const results = await mapWithConcurrency([3, 1, 2], 2, async (n) => {
      await new Promise((r) => setTimeout(r, n))
      return n * 10
    })
    assert.deepEqual(results, [30, 10, 20])
  })

  // The whole reason this exists: never have more than `limit` requests in flight at once
  // against a shared public API with no documented batch endpoint.
  test('never runs more than the given limit at once', async () => {
    let inFlight = 0
    let maxInFlight = 0
    await mapWithConcurrency([1, 2, 3, 4, 5, 6], 2, async () => {
      inFlight++
      maxInFlight = Math.max(maxInFlight, inFlight)
      await new Promise((r) => setTimeout(r, 1))
      inFlight--
    })
    assert.ok(maxInFlight <= 2, `expected at most 2 concurrent, saw ${maxInFlight}`)
  })
})

describe('geocodeWithGeoSearch', () => {
  const realFetch = globalThis.fetch
  afterEach(() => { globalThis.fetch = realFetch })

  // A validated match should be tagged with its source, so coordinate provenance is auditable.
  test('records a validated match with source "geosearch" and the matched address', async () => {
    globalThis.fetch = (async () => new Response(JSON.stringify({
      features: [{ geometry: { coordinates: [-74.003463, 40.713036] }, properties: { postalcode: '10007', housenumber: '1', label: '1 CENTER STREET, New York, NY, USA' } }],
    }))) as typeof fetch

    const results = await geocodeWithGeoSearch([{ id: 0, houseNumber: '1', street: '1 Centre St', city: 'New York', state: 'NY', zip: '10007' }])
    assert.deepEqual(results.get(0), { matched: true, lon: -74.003463, lat: 40.713036, source: 'geosearch', matchedAddress: '1 CENTER STREET, New York, NY, USA' })
  })

  // A wrong-house-number result must not count as matched, so the row still goes to Census, but
  // the point is kept in case Census can't place it either.
  test('keeps a wrong-house-number result as unmatched, with its point', async () => {
    globalThis.fetch = (async () => new Response(JSON.stringify({
      features: [{ geometry: { coordinates: [-73.95, 40.64] }, properties: { postalcode: '11226', housenumber: '1038', label: '1038 ROGERS AVENUE, Brooklyn, NY, USA' } }],
    }))) as typeof fetch

    const results = await geocodeWithGeoSearch([{ id: 0, houseNumber: '581', street: '581 Rogers Avenue', city: 'Brooklyn', state: 'NY', zip: '11226' }])
    assert.equal(results.get(0)?.matched, false)
    assert.equal(results.get(0)?.matchedAddress, '1038 ROGERS AVENUE, Brooklyn, NY, USA')
  })

  // An unvalidated (zip-mismatched) result must not appear in the map at all, so the caller's
  // "remaining" filter correctly sends this row on to the Census fallback.
  test('leaves no entry when the result fails zip validation', async () => {
    globalThis.fetch = (async () => new Response(JSON.stringify({
      features: [{ geometry: { coordinates: [-73.93931, 40.675917] }, properties: { postalcode: '11213' } }],
    }))) as typeof fetch

    const results = await geocodeWithGeoSearch([{ id: 0, street: '31 Albany Avenue', city: 'Kingston', state: 'NY', zip: '12401' }])
    assert.equal(results.has(0), false)
  })

  // A network failure on one row must not throw or block the others — it should just fall
  // through to Census like any other unresolved row.
  test('treats a failed request as unresolved rather than throwing', async () => {
    globalThis.fetch = (async () => { throw new Error('network down') }) as typeof fetch

    const results = await geocodeWithGeoSearch([{ id: 0, street: '1 Centre St', city: 'New York', state: 'NY', zip: '10007' }])
    assert.equal(results.has(0), false)
  })
})
