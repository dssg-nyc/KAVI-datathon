> **Product requirements document (PRD)** for the KAVI datathon, October 23–25. It describes what to build and why.
> For how to access the data, database and scripts, see [README.md](README.md).

<html><head></head><body><h1>PRD: NYC CVI Resource Connections Map</h1>
<h2>1. Engagement Summary</h2>
<p>Build a first-version interactive resource map for KAVI Brooklyn and other community violence intervention (CVI) organizations across New York City.</p>
<p>The map will turn the existing PDF-based “Connections Guide” into a searchable, geographic resource directory. It should help staff and community residents quickly find nearby services and support referrals between organizations.</p>
<p><strong>Current status:</strong> The Connections Guide has been extracted into a dataset, geocoded, and published to ArcGIS Online, along with public library, health facility, and cooling center layers. A small number of resources still need addresses or are hotlines without a physical location.<br>
<strong>Hackathon scope:</strong> Build the Stage 1 resource map on the published datasets, geocode the remaining resources, and add hotlines and other non-location resources to the directory.<br>
<strong>Future scope:</strong> Add needs, public-data, referral, and impact-measurement layers.</p>
<hr>
<h2>2. Problem Statement</h2>
<p>KAVI currently relies on a PDF resource guide and staff knowledge to identify services for participants. Case managers assess a participant’s needs, then manually locate and facilitate referrals to relevant organizations.</p>
<p>This approach creates several constraints:</p>
<ul>
<li>A PDF is difficult to search, browse, and use in real time with a participant.</li>
<li>It does not make nearby services immediately visible.</li>
<li>Resource knowledge can depend on individual staff relationships and familiarity.</li>
<li>Organizations serving neighboring catchment areas lack a shared, easy-to-use view of local resources.</li>
<li>The work CVI organizations perform beyond violence prevention is not systematically visible through current success measures.</li>
</ul>
<p>The data foundation is now in place. The Connections Guide has been converted into a geocoded dataset and published to ArcGIS Online, alongside public library, health facility, and cooling center layers. The remaining gap is a usable, searchable map that brings these layers together for staff and residents, plus a way to surface the hotlines and the few resources that still lack addresses.</p>
<hr>
<h2>3. Users</h2>
<h3>Primary users</h3>
<ul>
<li>
<p><strong>KAVI case managers and frontline staff</strong></p>
<ul>
<li>Identify services after intake.</li>
<li>Make referrals based on a participant’s stated needs and location.</li>
<li>Coordinate with neighboring CVI organizations.</li>
</ul>
</li>
<li>
<p><strong>Other NYC CVI organizations</strong></p>
<ul>
<li>Find resources in their catchment areas.</li>
<li>Support handoffs when participants live outside the organization’s primary geography.</li>
</ul>
</li>
</ul>
<h3>Secondary users</h3>
<ul>
<li><strong>Community residents</strong>
<ul>
<li>Independently find nearby resources.</li>
<li>View service details such as hours and eligibility information.</li>
</ul>
</li>
</ul>
<h3>Future users</h3>
<ul>
<li><strong>KAVI data staff and leadership</strong>
<ul>
<li>Understand referral patterns, service demand, and organizational impact.</li>
</ul>
</li>
<li><strong>Researchers and funders</strong>
<ul>
<li>Use aggregate, privacy-safe views of service coverage and community need.</li>
</ul>
</li>
</ul>
<hr>
<h2>4. Core User Journey</h2>
<ol>
<li>A participant comes to KAVI for support.</li>
<li>A case manager conducts intake and identifies needs—for example housing, employment, food assistance, mental-health support, childcare, or relocation.</li>
<li>The staff member searches the map by:
<ul>
<li>service type,</li>
<li>organization,</li>
<li>location,</li>
<li>and eventually catchment-area proxy such as police precinct.</li>
</ul>
</li>
<li>The map shows nearby eligible resources and their practical details.</li>
<li>The staff member makes a referral or coordinates a handoff to a CVI organization closer to the participant’s home.</li>
<li>In later phases, the referral and service category can contribute to aggregate impact reporting—without exposing participant-level information publicly.</li>
</ol>
<hr>
<h2>5. Main Pain Points</h2>
<h3>5.1 Static, manual resource discovery</h3>
<p>The current guide is a PDF. Staff must scroll, search manually, or rely on personal knowledge to identify appropriate referrals.</p>
<h3>5.2 Location is central to referral quality</h3>
<p>CVI organizations operate within defined catchment areas, described as roughly a 5–10 block radius. A service may be technically relevant but impractical if it is far from where a participant lives.</p>
<h3>5.3 Cross-organization coordination is harder than it needs to be</h3>
<p>KAVI may encounter a participant through its work in East Flatbush or Kings County Hospital even when that participant lives in another area, such as East New York or Bed-Stuy. A shared resource map would make it easier to coordinate a local handoff.</p>
<h3>5.4 Service work is under-measured</h3>
<p>Current violence-prevention evaluation is centered on shootings and recidivism. Jerome described a need to capture the broader range of services and referrals organizations provide.</p>
<h3>5.5 Small data capacity</h3>
<p>Jerome described the data team as 1.5 people, with him supported by a part-time colleague. KAVI needs a tool that is practical to maintain and does not create a major new reporting burden.</p>
<h3>5.6 Fragmented software environment</h3>
<p>KAVI uses multiple systems and expects to assess consolidation and better utilization in 2027. The map should avoid unnecessary duplication and be designed with future integration options in mind.</p>
<hr>
<h2>6. Product Goals</h2>
<h3>Stage 1: Hackathon MVP</h3>
<p>Deliver a usable interactive map that:</p>
<ul>
<li>Converts the existing Connections Guide into structured resource data.</li>
<li>Enables search by resource organization and service type.</li>
<li>Enables geographic filtering and map-based discovery.</li>
<li>Displays practical service information.</li>
<li>Supports rapid referrals by KAVI and other CVI organizations.</li>
<li>Is accessible via a shareable web link.</li>
</ul>
<h3>Stage 2: Future Product</h3>
<p>Expand the tool into a shared resource, planning, and impact platform that:</p>
<ul>
<li>Adds catchment-area and neighborhood data overlays.</li>
<li>Tracks aggregate referrals and service demand.</li>
<li>Helps organizations identify gaps between community needs and available services.</li>
<li>Supports broader impact storytelling beyond shootings and recidivism.</li>
</ul>
<hr>
<h2>7. Functional Requirements: Stage 1 MVP</h2>
<h3>7.1 Resource map</h3>
<ul>
<li>Display each resource as a map location.</li>
<li>Support NYC-wide coverage, with borough-level navigation.</li>
<li>Allow map zoom and pan.</li>
<li>Show the resource’s address and proximity to a searched location.</li>
<li>Display the published ArcGIS layers (see Section 8) as toggleable layers, with NYPL Connections as the primary resource layer.</li>
</ul>
<h3>7.2 Search</h3>
<p>Users should be able to search by:</p>
<ul>
<li>Organization name.</li>
<li>Service category.</li>
<li>Keyword.</li>
<li>Address, neighborhood, or ZIP code.</li>
<li>Borough.</li>
<li>Potentially police precinct, if that becomes the preferred geographic model for CVI catchment areas.</li>
</ul>
<h3>7.3 Service categories</h3>
<p>Initial categories should reflect the Connections Guide and Jerome’s examples, including:</p>
<ul>
<li>Housing assistance</li>
<li>Food assistance</li>
<li>Mental-health services</li>
<li>Childcare</li>
<li>Employment or job support</li>
<li>Reentry support</li>
<li>Public-health services</li>
<li>Other categories present in the source guide</li>
</ul>
<h3>7.4 Resource detail page or map card</h3>
<p>Each resource should include, where available:</p>
<ul>
<li>Organization name</li>
<li>Service categories</li>
<li>Address and map location</li>
<li>Phone number</li>
<li>Website or contact method</li>
<li>Hours and days of operation</li>
<li>Service availability</li>
<li>Eligibility criteria</li>
<li>Referral requirements</li>
<li>Notes or practical instructions</li>
<li>Source and last-updated date</li>
</ul>
<h3>7.5 Filters</h3>
<p>At minimum:</p>
<ul>
<li>Borough</li>
<li>Service category</li>
<li>Open/available status, if source data supports it</li>
<li>Organization type, where useful</li>
<li>Geography or catchment-area proxy</li>
</ul>
<h3>7.6 Shareability and access</h3>
<ul>
<li>Public or link-accessible web experience for community residents.</li>
<li>No participant-level records in the public map.</li>
<li>A simple URL that frontline staff can open during intake or outreach.</li>
</ul>
<h3>7.7 Hotlines and non-location resources</h3>
<ul>
<li>Display hotlines and other resources without a physical address in a searchable list alongside the map.</li>
<li>Tag these resources by service category so they appear in relevant searches and filters.</li>
<li>Clearly label them as citywide or phone-based so users do not expect a map location.</li>
</ul>
<hr>
<h2>8. Data Requirements</h2>
<h3>Initial data source</h3>
<p>The existing PDF Connections Guide is the initial authoritative input for the MVP. Its contents have been extracted into a tabular dataset and geocoded for mapping.</p>
<h3>Hackathon datasets</h3>
<p>The map datasets have been finalized and published to ArcGIS Online as hosted feature layers. Participants can download shapefiles from each layer’s service page during the hackathon. A mapping project overview document is available in the project Google Drive folder, which anyone with the link can open (<a href="https://drive.google.com/drive/folders/1f5QhMlY8pYgyomWSzPgYTBdnUUcBbUJS">link</a>).</p>
<ul>
<li><strong>NYPL Connections Geocoded</strong> (<a href="https://services6.arcgis.com/OO2s4OoyCZkYJ6oE/arcgis/rest/services/NYPL_Connections_merge/FeatureServer">link</a>)
<ul>
<li>Primary resource layer, geocoded from the Connections Guide.</li>
</ul>
</li>
<li><strong>Public Libraries</strong> (<a href="https://services6.arcgis.com/OO2s4OoyCZkYJ6oE/arcgis/rest/services/public_libraries_points/FeatureServer">link</a>)
<ul>
<li>Supplementary layer of library locations.</li>
</ul>
</li>
<li><strong>Health Facilities</strong> (<a href="https://services6.arcgis.com/OO2s4OoyCZkYJ6oE/arcgis/rest/services/health_facilities_points/FeatureServer">link</a>)
<ul>
<li>Supplementary layer of health facility locations.</li>
</ul>
</li>
<li><strong>Cooling Centers</strong> (<a href="https://services6.arcgis.com/OO2s4OoyCZkYJ6oE/arcgis/rest/services/Cooling_Sites_points/FeatureServer">link</a>)
<ul>
<li>Supplementary layer of cooling center locations.</li>
</ul>
</li>
</ul>
<h3>Known data gaps</h3>
<p>A small number of rows from the Connections Guide are not included in the geocoded layer, either because addresses could not be located before publication or because the resource is a hotline with no physical location. These rows are provided as CSV files in the project Google Drive folder (<a href="https://drive.google.com/drive/folders/1f5QhMlY8pYgyomWSzPgYTBdnUUcBbUJS">link</a>), along with the original dataset extracted from the Connections Guide PDF.</p>
<ul>
<li>Rows missing addresses can be researched and geocoded during the hackathon as a data-cleaning task.</li>
<li>Hotlines should remain in the directory as non-location resources (see Section 7.7).</li>
<li>Teams can compare the original dataset against the geocoded layer to confirm that no resources were dropped.</li>
</ul>
<h3>Suggested normalized fields</h3>

Field | Description
-- | --
Resource ID | Unique identifier
Organization name | Provider name
Service category | One or more standardized categories
Description | What the provider offers
Street address | Full address
Borough / neighborhood | Geographic metadata
Latitude / longitude | Map coordinates
Phone / website | Contact details
Hours | Days and operating times
Eligibility | Who can access services
Referral process | Walk-in, appointment, referral required, etc.
Languages | If available
Accessibility notes | If available
Last verified date | Recency and quality control
Source | Original PDF or later validation source


<h3>Current operating model</h3>
<ul>
<li>Case managers enter participant engagement, referrals, needs, goals, and case notes into Apricot 360.</li>
<li>Jerome administers the system and produces reporting.</li>
</ul>
<hr>
<h2>9. Future-State Architecture</h2>
<h3>Near-term</h3>
<ul>
<li>Public or link-accessible map and directory.</li>
<li>Structured resource database derived from the PDF.</li>
<li>Lightweight administrative process for updates.</li>
<li>No dependency on case-management data for the initial release.</li>
</ul>
<h3>Medium-term</h3>
<ul>
<li>Optional exports or integrations with Apricot 360 for aggregate referral reporting.</li>
<li>Geographic overlays from public datasets.</li>
<li>Organization-facing dashboard for trends, needs, and service coverage.</li>
<li>Clear governance around data access, privacy, maintenance, and ownership.</li>
</ul>
<h3>Longer-term</h3>
<ul>
<li>A deliberate AI and systems strategy across KAVI’s existing tools.</li>
<li>Platform rationalization: KAVI expects to assess whether it can reduce its number of systems to approximately three or four in 2027.</li>
</ul>
<hr>
<h2>10. Non-Functional Requirements</h2>
<ul>
<li><strong>Usability:</strong> Fast enough for frontline use during participant conversations.</li>
<li><strong>Mobile responsiveness:</strong> Must work on phones and tablets.</li>
<li><strong>Accessibility:</strong> Readable, navigable, and usable by community members.</li>
<li><strong>Maintainability:</strong> Updating a resource should not require engineering support.</li>
<li><strong>Scalability:</strong> Able to support additional resource categories, boroughs, and partner organizations.</li>
<li><strong>Privacy:</strong> Do not expose participant records or sensitive case information.</li>
<li><strong>Reliability:</strong> Clearly indicate when data was last verified.</li>
</ul>
<hr>
<h2>11. Out of Scope for the Hackathon MVP</h2>
<ul>
<li>Participant case management.</li>
<li>Storage of case notes.</li>
<li>Full referral workflow automation.</li>
<li>Cross-organization sharing of identifiable participant data.</li>
<li>Comprehensive impact dashboard.</li>
<li>Robust public-data overlays beyond the published ArcGIS layers.</li>
<li>A fully production-ready platform.</li>
</ul>
<p>Jerome explicitly framed the map itself as the useful first deliverable; impact metrics and broader functionality can be built later.</p>
<hr>
<h2>12. Success Criteria</h2>
<h3>MVP success</h3>
<ul>
<li>A staff member can search for housing, food, mental-health, childcare, or another listed service and find relevant nearby organizations.</li>
<li>A user can filter resources by useful geographic categories.</li>
<li>Resource cards show enough practical information to support a referral conversation.</li>
<li>Hotlines and other non-location resources are findable alongside mapped resources.</li>
<li>KAVI can share the map with CVI partners and community residents.</li>
<li>The map demonstrates a credible foundation for later analytics and impact layers.</li>
</ul>
<h3>Future success</h3>
<ul>
<li>CVI organizations can identify resource gaps by geography.</li>
<li>Organizations can show the range of services and referrals they facilitate.</li>
<li>The platform supports better coordination when participants receive services outside their home catchment area.</li>
<li>KAVI has a sustainable governance and maintenance model for data quality.</li>
</ul>
<hr>
<h2>13. Immediate Next Steps</h2>
<p><strong>Completed:</strong> The Connections Guide has been extracted into a dataset, geocoded, and published to ArcGIS Online alongside public library, health facility, and cooling center layers (see Section 8).</p>
<ol>
<li>Locate addresses for the remaining ungeocoded rows (see the missing-resources CSV files in the project Google Drive folder, <a href="https://drive.google.com/drive/folders/1f5QhMlY8pYgyomWSzPgYTBdnUUcBbUJS">link</a>) and add them to the NYPL Connections layer.</li>
<li>Decide how hotlines and other non-location resources will appear in the map interface.</li>
<li>Confirm the initial geography and filter model:
<ul>
<li>borough,</li>
<li>neighborhood,</li>
<li>police precinct,</li>
<li>CVI catchment area,</li>
<li>or a combination.</li>
</ul>
</li>
<li>Define the first list of service categories.</li>
<li>Identify which resource fields are reliably available in the extracted dataset.</li>
<li>Decide whether the MVP is public, link-accessible, or restricted to partner organizations.</li>
<li>Define a resource-update owner at KAVI.</li>
<li>Use this PRD as the project brief for hackathon volunteers.</li>
</ol></body></html>
