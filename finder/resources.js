// Loads public.resources from Supabase and turns each row into the record the finder filters on.
// Every value shown in the finder comes from these columns; nothing is guessed or joined from other sources.

export const COLUMNS = [
  'id', 'organization_name', 'street_number', 'street', 'address_line_2', 'city', 'state', 'zip_code',
  'phone_number', 'website', 'description', 'spanish_speaking', 'latitude', 'longitude', 'borough', 'row_type',
  'service_types_all', 'pdf_audiences',
].join(',');

export const BOROUGHS = ['Manhattan', 'Brooklyn', 'Queens', 'Bronx', 'Staten Island'];

// Map and tag colour per service_types_all value. A value missing here is drawn grey.
const SERVICE_COLORS = {
  'Health & Mental Health': '#CC79A7',
  'Legal & Rights': '#332288',
  Employment: '#56B4E9',
  Education: '#44AA99',
  Housing: '#0072B2',
  'Reentry Support': '#D55E00',
  'Financial Assistance': '#B8A11E',
  'Family & Childcare': '#117733',
  'Addiction & Recovery': '#882255',
  Food: '#E69F00',
};
export const serviceColor = (label) => SERVICE_COLORS[label] ?? '#6b7280';

// How someone reaches a resource that has no point on the map, by row_type.
const REMOTE_LABEL = { hotline: 'Hotline', web_only: 'Online', mailing_address: 'By mail or phone', outside_nyc: 'Outside NYC' };

const PAGE = 1000; // Supabase returns at most 1000 rows per request.

// Returns every row of public.resources. Throws the Supabase error object on failure.
export async function fetchRows(db) {
  const rows = [];
  for (let from = 0; ; from += PAGE) {
    const { data, error } = await db.from('resources').select(COLUMNS).order('id').range(from, from + PAGE - 1);
    if (error) throw error;
    rows.push(...data);
    if (data.length < PAGE) return rows;
  }
}

// cross_reference rows only point to another page of the guide ("See the full listing ... on page 305")
// and have no address, phone or website, so the finder leaves them out. Rows with no name, contact or
// description at all are left out too.
export function isListed(row) {
  if (row.row_type === 'cross_reference') return false;
  return [row.organization_name, row.phone_number, row.website, row.street, row.description].some(Boolean);
}

export function formatAddress(row) {
  const street = [row.street_number, row.street].filter(Boolean).join(' ');
  const cityLine = [row.city, [row.state, row.zip_code].filter(Boolean).join(' ')].filter(Boolean).join(', ');
  return [street, row.address_line_2, cityLine].filter(Boolean).join(', ');
}

// A resource is in person when it has coordinates (all mapped rows, plus the mailing_address and
// outside_nyc rows the geocoder placed). Everything else (hotline, web_only, and mailing_address or
// outside_nyc rows without coordinates) is reached by phone, mail or online.
export function toResource(row, index) {
  const inPerson = row.latitude != null && row.longitude != null;
  const name = row.organization_name?.trim() || '';
  const address = formatAddress(row);
  const description = row.description ?? '';
  return {
    index,
    id: row.id,
    name: name || '(No organization name)',
    hasName: Boolean(name),
    address,
    zip: row.zip_code ?? '',
    phone: row.phone_number ?? '',
    website: row.website ?? '',
    description,
    spanish: row.spanish_speaking === true,
    lat: inPerson ? row.latitude : null,
    lon: inPerson ? row.longitude : null,
    borough: row.borough,
    rowType: row.row_type,
    inPerson,
    remoteLabel: inPerson ? '' : REMOTE_LABEL[row.row_type] ?? 'Phone / online',
    services: row.service_types_all ?? [],
    audiences: row.pdf_audiences ?? [],
    color: serviceColor(row.service_types_all?.[0]),
    searchText: `${name} ${description}`.toLowerCase(),
  };
}

// The distinct values of a text[] field across resources, most common first.
export function distinctValues(resources, field) {
  const counts = new Map();
  for (const r of resources) for (const v of r[field]) counts.set(v, (counts.get(v) ?? 0) + 1);
  return [...counts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([v]) => v);
}
