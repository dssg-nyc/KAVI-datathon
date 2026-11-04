// The shapes the finder works with, as JSDoc types so editors can check uses of them.
// PublicRow mirrors pipeline/schemas/resources_public.json, the file the finder reads; keep the two in step.
// This file has no code: import it only for its types, `import('./types.js').PublicRow`.

/**
 * One row of data/public/resources.public.json, written by pipeline/6_build/build_data.ts.
 * Blank values are null. Lists are arrays of strings.
 * @typedef {object} PublicRow
 * @property {string} id stable id from data/resource_ids.csv: "176", "176-2", "feature-695"
 * @property {number | null} resource_id the row's position in the guide export; repeats for the NEON sites
 * @property {string | null} organization_name
 * @property {string | null} street_number
 * @property {string | null} street
 * @property {string | null} address_line_2
 * @property {string | null} city
 * @property {string | null} state
 * @property {string | null} zip_code
 * @property {string | null} phone_number
 * @property {string | null} website
 * @property {string | null} description
 * @property {boolean | null} spanish_speaking
 * @property {number | null} latitude
 * @property {number | null} longitude
 * @property {'Manhattan' | 'Brooklyn' | 'Queens' | 'Bronx' | 'Staten Island' | null} borough
 * @property {'mapped' | 'outside_nyc' | 'mailing_address' | 'hotline' | 'web_only' | 'cross_reference' | null} row_type
 * @property {string[] | null} service_types_all what the resource offers; drives "What kind of help?"
 * @property {string[] | null} audiences_all who it is for, ending in "Everyone" unless restricted
 * @property {string[] | null} restricted_audiences audiences it is only for
 * @property {string[] | null} focus_audiences audiences it was made for
 * @property {string[] | null} pdf_audiences audiences from the printed guide; the fallback for audiences_all
 */

/**
 * What app/lib/resources.js toResource() makes of a PublicRow: the record the finder filters and draws.
 * @typedef {object} Resource
 * @property {number} index position among the listed rows
 * @property {string | number} id
 * @property {string} name
 * @property {boolean} hasName
 * @property {string} address
 * @property {string} zip
 * @property {string} phone
 * @property {string} website
 * @property {string} description
 * @property {boolean} spanish
 * @property {number | null} lat
 * @property {number | null} lon
 * @property {string | null} borough
 * @property {string | null} rowType
 * @property {boolean} inPerson has a point on the map
 * @property {string} remoteLabel how to reach it when it is not in person
 * @property {string[]} services
 * @property {string[]} audiences without "Everyone"
 * @property {boolean} forEveryone
 * @property {string[]} madeFor restricted and focus audiences together
 * @property {string} color map pin and tag colour, from the first service
 * @property {string} searchText name and description, lower-cased
 */

export {};
