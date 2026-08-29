import { pgTable, unique, serial, text, char, timestamp, index, foreignKey, integer, numeric, boolean, check, jsonb, smallint, bigserial, bigint, uuid, date, uniqueIndex, primaryKey, pgEnum } from "drizzle-orm/pg-core"
import { sql } from "drizzle-orm"
import { citext, tsvector } from "./custom-types";

export const alertFrequency = pgEnum("alert_frequency", ['Instant', 'Daily', 'Weekly'])
export const developmentStatus = pgEnum("development_status", ['Planning', 'UnderConstruction', 'Completed'])
export const enquirySource = pgEnum("enquiry_source", ['Website', 'MobileApp', 'Partner', 'Phone', 'WalkIn'])
export const enquiryStatus = pgEnum("enquiry_status", ['New', 'Contacted', 'Closed', 'Spam'])
export const feedFormat = pgEnum("feed_format", ['XML', 'JSON', 'CSV', 'API'])
export const importJobStatus = pgEnum("import_job_status", ['Pending', 'Running', 'Success', 'PartialSuccess', 'Failed'])
export const listingMediaType = pgEnum("listing_media_type", ['Photo', 'FloorPlan', 'VirtualTour', 'Video', 'Document'])
export const listingStatus = pgEnum("listing_status", ['Active', 'UnderOffer', 'Sold', 'Rented', 'Expired', 'Withdrawn', 'Draft'])
export const listingType = pgEnum("listing_type", ['Sale', 'Rental', 'Unknown'])
export const priceAlertType = pgEnum("price_alert_type", ['PriceDrop', 'PriceIncrease', 'NewMatchingListing', 'BackOnMarket'])
export const priceChangeType = pgEnum("price_change_type", ['Initial', 'Increase', 'Decrease', 'Relisted'])
export const rentalPeriod = pgEnum("rental_period", ['Monthly', 'Weekly', 'Daily'])
export const reviewStatus = pgEnum("review_status", ['Pending', 'Published', 'Rejected'])


export const provinces = pgTable("provinces", {
	id: serial().primaryKey().notNull(),
	name: text().notNull(),
	code: text().notNull(),
	countryCode: char("country_code", { length: 2 }).default('ZA').notNull(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
}, (table) => [
	unique("uq_provinces_name").on(table.name, table.countryCode),
	unique("uq_provinces_code").on(table.code, table.countryCode),
]);

export const cities = pgTable("cities", {
	id: serial().primaryKey().notNull(),
	provinceId: integer("province_id").notNull(),
	name: text().notNull(),
	slug: text().notNull(),
	latitude: numeric({ precision: 9, scale:  6 }),
	longitude: numeric({ precision: 9, scale:  6 }),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
}, (table) => [
	index("idx_cities_province_id").using("btree", table.provinceId.asc().nullsLast().op("int4_ops")),
	foreignKey({
			columns: [table.provinceId],
			foreignColumns: [provinces.id],
			name: "cities_province_id_fkey"
		}).onDelete("restrict"),
	unique("uq_cities_province_name").on(table.provinceId, table.name),
	unique("uq_cities_province_slug").on(table.provinceId, table.slug),
]);

export const suburbs = pgTable("suburbs", {
	id: serial().primaryKey().notNull(),
	cityId: integer("city_id").notNull(),
	name: text().notNull(),
	slug: text().notNull(),
	postalCode: text("postal_code"),
	latitude: numeric({ precision: 9, scale:  6 }),
	longitude: numeric({ precision: 9, scale:  6 }),
	isActive: boolean("is_active").default(true).notNull(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
}, (table) => [
	index("idx_suburbs_city_id").using("btree", table.cityId.asc().nullsLast().op("int4_ops")),
	index("idx_suburbs_name_trgm").using("gin", table.name.asc().nullsLast().op("gin_trgm_ops")),
	foreignKey({
			columns: [table.cityId],
			foreignColumns: [cities.id],
			name: "suburbs_city_id_fkey"
		}).onDelete("restrict"),
	unique("uq_suburbs_city_name").on(table.cityId, table.name),
	unique("uq_suburbs_city_slug").on(table.cityId, table.slug),
]);

export const feedSources = pgTable("feed_sources", {
	id: serial().primaryKey().notNull(),
	code: text().notNull(),
	name: text().notNull(),
	vendorName: text("vendor_name").notNull(),
	format: feedFormat().default('XML').notNull(),
	baseUrl: text("base_url"),
	authConfig: jsonb("auth_config").default({}).notNull(),
	ttlMinutes: integer("ttl_minutes").default(1440).notNull(),
	isActive: boolean("is_active").default(true).notNull(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
}, (table) => [
	unique("uq_feed_sources_code").on(table.code),
	check("feed_sources_ttl_minutes_check", sql`ttl_minutes > 0`),
]);

export const propertyTypes = pgTable("property_types", {
	id: serial().primaryKey().notNull(),
	name: text().notNull(),
	slug: text().notNull(),
	category: text().default('Residential').notNull(),
	isActive: boolean("is_active").default(true).notNull(),
	sortOrder: smallint("sort_order").default(0).notNull(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
}, (table) => [
	unique("uq_property_types_name").on(table.name),
	unique("uq_property_types_slug").on(table.slug),
	check("property_types_category_check", sql`category = ANY (ARRAY['Residential'::text, 'Commercial'::text, 'Agricultural'::text, 'Land'::text])`),
]);

export const importJobs = pgTable("import_jobs", {
	id: bigserial({ mode: "bigint" }).primaryKey().notNull(),
	feedSourceId: integer("feed_source_id").notNull(),
	status: importJobStatus().default('Pending').notNull(),
	startedAt: timestamp("started_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
	finishedAt: timestamp("finished_at", { withTimezone: true, mode: 'string' }),
	recordsSeen: integer("records_seen").default(0).notNull(),
	recordsInserted: integer("records_inserted").default(0).notNull(),
	recordsUpdated: integer("records_updated").default(0).notNull(),
	recordsExpired: integer("records_expired").default(0).notNull(),
	recordsFailed: integer("records_failed").default(0).notNull(),
	fileReference: text("file_reference"),
	checksum: text(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
}, (table) => [
	index("idx_import_jobs_feed_source_started").using("btree", table.feedSourceId.asc().nullsLast().op("int4_ops"), table.startedAt.desc().nullsFirst().op("int4_ops")),
	index("idx_import_jobs_status").using("btree", table.status.asc().nullsLast().op("enum_ops")).where(sql`(status = ANY (ARRAY['Pending'::import_job_status, 'Running'::import_job_status]))`),
	foreignKey({
			columns: [table.feedSourceId],
			foreignColumns: [feedSources.id],
			name: "import_jobs_feed_source_id_fkey"
		}).onDelete("cascade"),
]);

export const importErrors = pgTable("import_errors", {
	id: bigserial({ mode: "bigint" }).primaryKey().notNull(),
	// You can use { mode: "bigint" } if numbers are exceeding js number limitations
	importJobId: bigint("import_job_id", { mode: "number" }).notNull(),
	feedSourceId: integer("feed_source_id").notNull(),
	vendorListingId: text("vendor_listing_id"),
	errorType: text("error_type").notNull(),
	errorMessage: text("error_message").notNull(),
	rawPayload: jsonb("raw_payload"),
	occurredAt: timestamp("occurred_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
}, (table) => [
	index("idx_import_errors_feed_source_occurred").using("btree", table.feedSourceId.asc().nullsLast().op("int4_ops"), table.occurredAt.desc().nullsFirst().op("int4_ops")),
	index("idx_import_errors_job_id").using("btree", table.importJobId.asc().nullsLast().op("int8_ops")),
	foreignKey({
			columns: [table.importJobId],
			foreignColumns: [importJobs.id],
			name: "import_errors_import_job_id_fkey"
		}).onDelete("cascade"),
	foreignKey({
			columns: [table.feedSourceId],
			foreignColumns: [feedSources.id],
			name: "import_errors_feed_source_id_fkey"
		}).onDelete("cascade"),
]);

export const agencies = pgTable("agencies", {
	id: uuid().defaultRandom().primaryKey().notNull(),
	name: text().notNull(),
	tradingName: text("trading_name"),
	registrationNumber: text("registration_number"),
	franchiseGroup: text("franchise_group"),
	email: citext("email"),
	phone: text(),
	website: text(),
	logoUrl: text("logo_url"),
	suburbId: integer("suburb_id"),
	streetAddress: text("street_address"),
	status: text().default('Active').notNull(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
}, (table) => [
	index("idx_agencies_name_trgm").using("gin", table.name.asc().nullsLast().op("gin_trgm_ops")),
	index("idx_agencies_suburb_id").using("btree", table.suburbId.asc().nullsLast().op("int4_ops")),
	foreignKey({
			columns: [table.suburbId],
			foreignColumns: [suburbs.id],
			name: "agencies_suburb_id_fkey"
		}).onDelete("set null"),
	unique("uq_agencies_registration_number").on(table.registrationNumber),
	check("agencies_status_check", sql`status = ANY (ARRAY['Active'::text, 'Inactive'::text, 'Suspended'::text])`),
]);

export const agencyVendorIds = pgTable("agency_vendor_ids", {
	id: bigserial({ mode: "bigint" }).primaryKey().notNull(),
	agencyId: uuid("agency_id").notNull(),
	feedSourceId: integer("feed_source_id").notNull(),
	vendorAgencyId: text("vendor_agency_id").notNull(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
}, (table) => [
	index("idx_agency_vendor_ids_agency_id").using("btree", table.agencyId.asc().nullsLast().op("uuid_ops")),
	foreignKey({
			columns: [table.agencyId],
			foreignColumns: [agencies.id],
			name: "agency_vendor_ids_agency_id_fkey"
		}).onDelete("cascade"),
	foreignKey({
			columns: [table.feedSourceId],
			foreignColumns: [feedSources.id],
			name: "agency_vendor_ids_feed_source_id_fkey"
		}).onDelete("cascade"),
	unique("uq_agency_vendor_ids").on(table.feedSourceId, table.vendorAgencyId),
]);

export const enquiries = pgTable("enquiries", {
	id: uuid().defaultRandom().primaryKey().notNull(),
	listingId: uuid("listing_id").notNull(),
	agencyId: uuid("agency_id"),
	agentId: uuid("agent_id"),
	userId: uuid("user_id"),
	name: text().notNull(),
	email: citext("email"),
	phone: text(),
	message: text(),
	source: enquirySource().default('Website').notNull(),
	status: enquiryStatus().default('New').notNull(),
	respondedAt: timestamp("responded_at", { withTimezone: true, mode: 'string' }),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
}, (table) => [
	index("idx_enquiries_agent_id").using("btree", table.agentId.asc().nullsLast().op("timestamptz_ops"), table.createdAt.desc().nullsFirst().op("timestamptz_ops")),
	index("idx_enquiries_listing_id").using("btree", table.listingId.asc().nullsLast().op("timestamptz_ops"), table.createdAt.desc().nullsFirst().op("timestamptz_ops")),
	index("idx_enquiries_status").using("btree", table.status.asc().nullsLast().op("enum_ops")).where(sql`(status = 'New'::enquiry_status)`),
	foreignKey({
			columns: [table.listingId],
			foreignColumns: [listings.id],
			name: "enquiries_listing_id_fkey"
		}).onDelete("cascade"),
	foreignKey({
			columns: [table.agencyId],
			foreignColumns: [agencies.id],
			name: "enquiries_agency_id_fkey"
		}).onDelete("set null"),
	foreignKey({
			columns: [table.agentId],
			foreignColumns: [agents.id],
			name: "enquiries_agent_id_fkey"
		}).onDelete("set null"),
	foreignKey({
			columns: [table.userId],
			foreignColumns: [users.id],
			name: "enquiries_user_id_fkey"
		}).onDelete("set null"),
	check("ck_enquiries_has_contact", sql`(email IS NOT NULL) OR (phone IS NOT NULL)`),
]);

export const agents = pgTable("agents", {
	id: uuid().defaultRandom().primaryKey().notNull(),
	agencyId: uuid("agency_id"),
	firstName: text("first_name").notNull(),
	lastName: text("last_name").notNull(),
	displayName: text("display_name"),
	email: citext("email"),
	phone: text(),
	mobile: text(),
	photoUrl: text("photo_url"),
	bio: text(),
	ficaVerified: boolean("fica_verified").default(false).notNull(),
	status: text().default('Active').notNull(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
}, (table) => [
	index("idx_agents_agency_id").using("btree", table.agencyId.asc().nullsLast().op("uuid_ops")),
	index("idx_agents_name_trgm").using("gin", sql`(((first_name || ' '::text) || last_name))`),
	foreignKey({
			columns: [table.agencyId],
			foreignColumns: [agencies.id],
			name: "agents_agency_id_fkey"
		}).onDelete("set null"),
	check("agents_status_check", sql`status = ANY (ARRAY['Active'::text, 'Inactive'::text, 'Suspended'::text])`),
]);

export const agentVendorIds = pgTable("agent_vendor_ids", {
	id: bigserial({ mode: "bigint" }).primaryKey().notNull(),
	agentId: uuid("agent_id").notNull(),
	feedSourceId: integer("feed_source_id").notNull(),
	vendorAgentId: text("vendor_agent_id").notNull(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
}, (table) => [
	index("idx_agent_vendor_ids_agent_id").using("btree", table.agentId.asc().nullsLast().op("uuid_ops")),
	foreignKey({
			columns: [table.agentId],
			foreignColumns: [agents.id],
			name: "agent_vendor_ids_agent_id_fkey"
		}).onDelete("cascade"),
	foreignKey({
			columns: [table.feedSourceId],
			foreignColumns: [feedSources.id],
			name: "agent_vendor_ids_feed_source_id_fkey"
		}).onDelete("cascade"),
	unique("uq_agent_vendor_ids").on(table.feedSourceId, table.vendorAgentId),
]);

export const developments = pgTable("developments", {
	id: uuid().defaultRandom().primaryKey().notNull(),
	name: text().notNull(),
	slug: text().notNull(),
	developerName: text("developer_name"),
	description: text(),
	suburbId: integer("suburb_id").notNull(),
	status: developmentStatus().default('Planning').notNull(),
	completionDate: date("completion_date"),
	totalUnits: integer("total_units"),
	unitsAvailable: integer("units_available"),
	priceFrom: numeric("price_from", { precision: 14, scale:  2 }),
	priceTo: numeric("price_to", { precision: 14, scale:  2 }),
	primaryImageUrl: text("primary_image_url"),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
}, (table) => [
	index("idx_developments_suburb_id").using("btree", table.suburbId.asc().nullsLast().op("int4_ops")),
	foreignKey({
			columns: [table.suburbId],
			foreignColumns: [suburbs.id],
			name: "developments_suburb_id_fkey"
		}).onDelete("restrict"),
	unique("uq_developments_slug").on(table.slug),
	check("developments_total_units_check", sql`(total_units IS NULL) OR (total_units >= 0)`),
	check("developments_units_available_check", sql`(units_available IS NULL) OR (units_available >= 0)`),
	check("developments_price_from_check", sql`(price_from IS NULL) OR (price_from >= (0)::numeric)`),
	check("developments_price_to_check", sql`(price_to IS NULL) OR (price_to >= (0)::numeric)`),
	check("ck_developments_unit_counts", sql`(units_available IS NULL) OR (total_units IS NULL) OR (units_available <= total_units)`),
	check("ck_developments_price_range", sql`(price_from IS NULL) OR (price_to IS NULL) OR (price_from <= price_to)`),
]);

export const listings = pgTable("listings", {
	id: uuid().defaultRandom().primaryKey().notNull(),
	feedSourceId: integer("feed_source_id").notNull(),
	vendorListingId: text("vendor_listing_id").notNull(),
	agencyId: uuid("agency_id"),
	agentId: uuid("agent_id"),
	developmentId: uuid("development_id"),
	propertyTypeId: integer("property_type_id").notNull(),
	suburbId: integer("suburb_id").notNull(),
	listingType: listingType("listing_type").default('Unknown').notNull(),
	status: listingStatus().default('Active').notNull(),
	price: numeric({ precision: 14, scale:  2 }),
	priceOnApplication: boolean("price_on_application").default(false).notNull(),
	currency: char({ length: 3 }).default('ZAR').notNull(),
	bedrooms: smallint(),
	bathrooms: numeric({ precision: 3, scale:  1 }),
	garages: smallint(),
	parkingSpaces: smallint("parking_spaces"),
	erfSizeSqm: numeric("erf_size_sqm", { precision: 10, scale:  2 }),
	floorSizeSqm: numeric("floor_size_sqm", { precision: 10, scale:  2 }),
	levies: numeric({ precision: 10, scale:  2 }),
	ratesAndTaxes: numeric("rates_and_taxes", { precision: 10, scale:  2 }),
	title: text().notNull(),
	description: text(),
	streetAddress: text("street_address"),
	complexName: text("complex_name"),
	unitNumber: text("unit_number"),
	latitude: numeric({ precision: 9, scale:  6 }),
	longitude: numeric({ precision: 9, scale:  6 }),
	features: text().array().default([""]).notNull(),
	primaryImageUrl: text("primary_image_url"),
	isFeatured: boolean("is_featured").default(false).notNull(),
	searchVector: tsvector("search_vector").generatedAlwaysAs(sql`(((setweight(to_tsvector('english'::regconfig, COALESCE(title, ''::text)), 'A'::"char") || setweight(to_tsvector('english'::regconfig, COALESCE(complex_name, ''::text)), 'B'::"char")) || setweight(to_tsvector('english'::regconfig, COALESCE(street_address, ''::text)), 'B'::"char")) || setweight(to_tsvector('english'::regconfig, COALESCE(description, ''::text)), 'C'::"char"))`),
	listedAt: timestamp("listed_at", { withTimezone: true, mode: 'string' }),
	lastUpdatedByVendorAt: timestamp("last_updated_by_vendor_at", { withTimezone: true, mode: 'string' }),
	firstImportedAt: timestamp("first_imported_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
	lastSeenAt: timestamp("last_seen_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
	expiresAt: timestamp("expires_at", { withTimezone: true, mode: 'string' }).default(sql`(now() + '1 day'::interval)`).notNull(),
	expiredAt: timestamp("expired_at", { withTimezone: true, mode: 'string' }),
	rawData: jsonb("raw_data").default({}).notNull(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
}, (table) => [
	index("idx_listings_active_bedrooms").using("btree", table.listingType.asc().nullsLast().op("int2_ops"), table.bedrooms.asc().nullsLast().op("enum_ops")).where(sql`(status = 'Active'::listing_status)`),
	index("idx_listings_active_price").using("btree", table.listingType.asc().nullsLast().op("enum_ops"), table.price.asc().nullsLast().op("enum_ops")).where(sql`(status = 'Active'::listing_status)`),
	index("idx_listings_agency_id").using("btree", table.agencyId.asc().nullsLast().op("uuid_ops")),
	index("idx_listings_agent_id").using("btree", table.agentId.asc().nullsLast().op("uuid_ops")),
	index("idx_listings_development_id").using("btree", table.developmentId.asc().nullsLast().op("uuid_ops")).where(sql`(development_id IS NOT NULL)`),
	index("idx_listings_expiry_sweep").using("btree", table.expiresAt.asc().nullsLast().op("timestamptz_ops")).where(sql`(status = 'Active'::listing_status)`),
	index("idx_listings_features_gin").using("gin", table.features.asc().nullsLast().op("array_ops")),
	index("idx_listings_property_type_id").using("btree", table.propertyTypeId.asc().nullsLast().op("int4_ops")),
	index("idx_listings_raw_data_gin").using("gin", table.rawData.asc().nullsLast().op("jsonb_path_ops")),
	index("idx_listings_search_primary").using("btree", table.suburbId.asc().nullsLast().op("int4_ops"), table.listingType.asc().nullsLast().op("enum_ops"), table.status.asc().nullsLast().op("numeric_ops"), table.price.asc().nullsLast().op("enum_ops")),
	index("idx_listings_search_vector_gin").using("gin", table.searchVector.asc().nullsLast().op("tsvector_ops")),
	foreignKey({
			columns: [table.propertyTypeId],
			foreignColumns: [propertyTypes.id],
			name: "listings_property_type_id_fkey"
		}).onDelete("restrict"),
	foreignKey({
			columns: [table.suburbId],
			foreignColumns: [suburbs.id],
			name: "listings_suburb_id_fkey"
		}).onDelete("restrict"),
	foreignKey({
			columns: [table.feedSourceId],
			foreignColumns: [feedSources.id],
			name: "listings_feed_source_id_fkey"
		}).onDelete("restrict"),
	foreignKey({
			columns: [table.agencyId],
			foreignColumns: [agencies.id],
			name: "listings_agency_id_fkey"
		}).onDelete("set null"),
	foreignKey({
			columns: [table.agentId],
			foreignColumns: [agents.id],
			name: "listings_agent_id_fkey"
		}).onDelete("set null"),
	foreignKey({
			columns: [table.developmentId],
			foreignColumns: [developments.id],
			name: "listings_development_id_fkey"
		}).onDelete("set null"),
	unique("uq_listings_feed_vendor").on(table.feedSourceId, table.vendorListingId),
	check("listings_price_check", sql`(price IS NULL) OR (price >= (0)::numeric)`),
	check("listings_bedrooms_check", sql`(bedrooms IS NULL) OR (bedrooms >= 0)`),
	check("listings_bathrooms_check", sql`(bathrooms IS NULL) OR (bathrooms >= (0)::numeric)`),
	check("listings_garages_check", sql`(garages IS NULL) OR (garages >= 0)`),
	check("listings_parking_spaces_check", sql`(parking_spaces IS NULL) OR (parking_spaces >= 0)`),
	check("listings_erf_size_sqm_check", sql`(erf_size_sqm IS NULL) OR (erf_size_sqm >= (0)::numeric)`),
	check("listings_floor_size_sqm_check", sql`(floor_size_sqm IS NULL) OR (floor_size_sqm >= (0)::numeric)`),
	check("listings_levies_check", sql`(levies IS NULL) OR (levies >= (0)::numeric)`),
	check("listings_rates_and_taxes_check", sql`(rates_and_taxes IS NULL) OR (rates_and_taxes >= (0)::numeric)`),
]);

export const listingRentalDetails = pgTable("listing_rental_details", {
	listingId: uuid("listing_id").primaryKey().notNull(),
	rentalPeriod: rentalPeriod("rental_period").default('Monthly').notNull(),
	depositAmount: numeric("deposit_amount", { precision: 12, scale:  2 }),
	availableFrom: date("available_from"),
	leaseTermMonths: smallint("lease_term_months"),
	furnished: boolean().default(false).notNull(),
	petFriendly: boolean("pet_friendly").default(false).notNull(),
	utilitiesIncluded: boolean("utilities_included").default(false).notNull(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
}, (table) => [
	foreignKey({
			columns: [table.listingId],
			foreignColumns: [listings.id],
			name: "listing_rental_details_listing_id_fkey"
		}).onDelete("cascade"),
	check("listing_rental_details_deposit_amount_check", sql`(deposit_amount IS NULL) OR (deposit_amount >= (0)::numeric)`),
	check("listing_rental_details_lease_term_months_check", sql`(lease_term_months IS NULL) OR (lease_term_months > 0)`),
]);

export const listingMedia = pgTable("listing_media", {
	id: bigserial({ mode: "bigint" }).primaryKey().notNull(),
	listingId: uuid("listing_id").notNull(),
	mediaType: listingMediaType("media_type").default('Photo').notNull(),
	url: text().notNull(),
	caption: text(),
	displayOrder: smallint("display_order").default(0).notNull(),
	widthPx: integer("width_px"),
	heightPx: integer("height_px"),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
}, (table) => [
	index("idx_listing_media_listing_id").using("btree", table.listingId.asc().nullsLast().op("enum_ops"), table.mediaType.asc().nullsLast().op("int2_ops"), table.displayOrder.asc().nullsLast().op("enum_ops")),
	foreignKey({
			columns: [table.listingId],
			foreignColumns: [listings.id],
			name: "listing_media_listing_id_fkey"
		}).onDelete("cascade"),
	unique("uq_listing_media_listing_url").on(table.listingId, table.url),
]);

export const listingPriceHistory = pgTable("listing_price_history", {
	id: bigserial({ mode: "bigint" }).primaryKey().notNull(),
	listingId: uuid("listing_id").notNull(),
	oldPrice: numeric("old_price", { precision: 14, scale:  2 }),
	newPrice: numeric("new_price", { precision: 14, scale:  2 }),
	changeType: priceChangeType("change_type").notNull(),
	// You can use { mode: "bigint" } if numbers are exceeding js number limitations
	importJobId: bigint("import_job_id", { mode: "number" }),
	changedAt: timestamp("changed_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
}, (table) => [
	index("idx_listing_price_history_listing_id").using("btree", table.listingId.asc().nullsLast().op("timestamptz_ops"), table.changedAt.desc().nullsFirst().op("timestamptz_ops")),
	foreignKey({
			columns: [table.listingId],
			foreignColumns: [listings.id],
			name: "listing_price_history_listing_id_fkey"
		}).onDelete("cascade"),
	foreignKey({
			columns: [table.importJobId],
			foreignColumns: [importJobs.id],
			name: "listing_price_history_import_job_id_fkey"
		}).onDelete("set null"),
]);

export const users = pgTable("users", {
	id: uuid().defaultRandom().primaryKey().notNull(),
	email: citext("email").notNull(),
	phone: text(),
	firstName: text("first_name"),
	lastName: text("last_name"),
	passwordHash: text("password_hash"),
	isEmailVerified: boolean("is_email_verified").default(false).notNull(),
	marketingOptIn: boolean("marketing_opt_in").default(false).notNull(),
	lastLoginAt: timestamp("last_login_at", { withTimezone: true, mode: 'string' }),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
}, (table) => [
	unique("uq_users_email").on(table.email),
]);

export const savedSearches = pgTable("saved_searches", {
	id: uuid().defaultRandom().primaryKey().notNull(),
	userId: uuid("user_id").notNull(),
	name: text().notNull(),
	filters: jsonb().default({}).notNull(),
	listingType: listingType("listing_type").default('Unknown').notNull(),
	notifyFrequency: alertFrequency("notify_frequency").default('Daily').notNull(),
	isActive: boolean("is_active").default(true).notNull(),
	lastNotifiedAt: timestamp("last_notified_at", { withTimezone: true, mode: 'string' }),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
}, (table) => [
	index("idx_saved_searches_active_notify").using("btree", table.notifyFrequency.asc().nullsLast().op("enum_ops")).where(sql`(is_active = true)`),
	index("idx_saved_searches_filters_gin").using("gin", table.filters.asc().nullsLast().op("jsonb_path_ops")),
	index("idx_saved_searches_user_id").using("btree", table.userId.asc().nullsLast().op("uuid_ops")),
	foreignKey({
			columns: [table.userId],
			foreignColumns: [users.id],
			name: "saved_searches_user_id_fkey"
		}).onDelete("cascade"),
]);

export const listingFavourites = pgTable("listing_favourites", {
	id: uuid().defaultRandom().primaryKey().notNull(),
	userId: uuid("user_id").notNull(),
	listingId: uuid("listing_id").notNull(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
}, (table) => [
	index("idx_listing_favourites_listing_id").using("btree", table.listingId.asc().nullsLast().op("uuid_ops")),
	foreignKey({
			columns: [table.userId],
			foreignColumns: [users.id],
			name: "listing_favourites_user_id_fkey"
		}).onDelete("cascade"),
	foreignKey({
			columns: [table.listingId],
			foreignColumns: [listings.id],
			name: "listing_favourites_listing_id_fkey"
		}).onDelete("cascade"),
	unique("uq_listing_favourites_user_listing").on(table.userId, table.listingId),
]);

export const priceAlerts = pgTable("price_alerts", {
	id: uuid().defaultRandom().primaryKey().notNull(),
	userId: uuid("user_id").notNull(),
	savedSearchId: uuid("saved_search_id"),
	listingId: uuid("listing_id"),
	alertType: priceAlertType("alert_type").notNull(),
	targetPrice: numeric("target_price", { precision: 14, scale:  2 }),
	isActive: boolean("is_active").default(true).notNull(),
	lastTriggeredAt: timestamp("last_triggered_at", { withTimezone: true, mode: 'string' }),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
}, (table) => [
	index("idx_price_alerts_active").using("btree", table.alertType.asc().nullsLast().op("enum_ops")).where(sql`(is_active = true)`),
	index("idx_price_alerts_listing_id").using("btree", table.listingId.asc().nullsLast().op("uuid_ops")).where(sql`(listing_id IS NOT NULL)`),
	index("idx_price_alerts_user_id").using("btree", table.userId.asc().nullsLast().op("uuid_ops")),
	foreignKey({
			columns: [table.userId],
			foreignColumns: [users.id],
			name: "price_alerts_user_id_fkey"
		}).onDelete("cascade"),
	foreignKey({
			columns: [table.savedSearchId],
			foreignColumns: [savedSearches.id],
			name: "price_alerts_saved_search_id_fkey"
		}).onDelete("cascade"),
	foreignKey({
			columns: [table.listingId],
			foreignColumns: [listings.id],
			name: "price_alerts_listing_id_fkey"
		}).onDelete("cascade"),
	check("price_alerts_target_price_check", sql`(target_price IS NULL) OR (target_price >= (0)::numeric)`),
	check("ck_price_alerts_target", sql`((saved_search_id IS NOT NULL) AND (listing_id IS NULL)) OR ((saved_search_id IS NULL) AND (listing_id IS NOT NULL))`),
]);

export const agentReviews = pgTable("agent_reviews", {
	id: uuid().defaultRandom().primaryKey().notNull(),
	agentId: uuid("agent_id").notNull(),
	reviewerUserId: uuid("reviewer_user_id"),
	relatedListingId: uuid("related_listing_id"),
	rating: smallint().notNull(),
	title: text(),
	body: text(),
	isVerifiedBuyer: boolean("is_verified_buyer").default(false).notNull(),
	status: reviewStatus().default('Pending').notNull(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
}, (table) => [
	index("idx_agent_reviews_agent_id").using("btree", table.agentId.asc().nullsLast().op("uuid_ops")).where(sql`(status = 'Published'::review_status)`),
	foreignKey({
			columns: [table.agentId],
			foreignColumns: [agents.id],
			name: "agent_reviews_agent_id_fkey"
		}).onDelete("cascade"),
	foreignKey({
			columns: [table.reviewerUserId],
			foreignColumns: [users.id],
			name: "agent_reviews_reviewer_user_id_fkey"
		}).onDelete("set null"),
	foreignKey({
			columns: [table.relatedListingId],
			foreignColumns: [listings.id],
			name: "agent_reviews_related_listing_id_fkey"
		}).onDelete("set null"),
	unique("uq_agent_reviews_reviewer_agent_listing").on(table.agentId, table.reviewerUserId, table.relatedListingId),
	check("agent_reviews_rating_check", sql`(rating >= 1) AND (rating <= 5)`),
]);

export const suburbPriceMonthly = pgTable("suburb_price_monthly", {
	id: bigserial({ mode: "bigint" }).primaryKey().notNull(),
	suburbId: integer("suburb_id").notNull(),
	listingType: listingType("listing_type").notNull(),
	propertyTypeId: integer("property_type_id"),
	periodMonth: date("period_month").notNull(),
	medianPrice: numeric("median_price", { precision: 14, scale:  2 }),
	avgPrice: numeric("avg_price", { precision: 14, scale:  2 }),
	minPrice: numeric("min_price", { precision: 14, scale:  2 }),
	maxPrice: numeric("max_price", { precision: 14, scale:  2 }),
	medianPricePerSqm: numeric("median_price_per_sqm", { precision: 12, scale:  2 }),
	listingCount: integer("listing_count").default(0).notNull(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
}, (table) => [
	index("idx_suburb_price_monthly_suburb_period").using("btree", table.suburbId.asc().nullsLast().op("enum_ops"), table.listingType.asc().nullsLast().op("int4_ops"), table.periodMonth.desc().nullsFirst().op("date_ops")),
	uniqueIndex("uq_suburb_price_monthly_overall").using("btree", table.suburbId.asc().nullsLast().op("int4_ops"), table.listingType.asc().nullsLast().op("int4_ops"), table.periodMonth.asc().nullsLast().op("enum_ops")).where(sql`(property_type_id IS NULL)`),
	uniqueIndex("uq_suburb_price_monthly_with_type").using("btree", table.suburbId.asc().nullsLast().op("int4_ops"), table.listingType.asc().nullsLast().op("int4_ops"), table.propertyTypeId.asc().nullsLast().op("enum_ops"), table.periodMonth.asc().nullsLast().op("enum_ops")).where(sql`(property_type_id IS NOT NULL)`),
	foreignKey({
			columns: [table.suburbId],
			foreignColumns: [suburbs.id],
			name: "suburb_price_monthly_suburb_id_fkey"
		}).onDelete("cascade"),
	foreignKey({
			columns: [table.propertyTypeId],
			foreignColumns: [propertyTypes.id],
			name: "suburb_price_monthly_property_type_id_fkey"
		}).onDelete("cascade"),
	check("ck_suburb_price_monthly_period_is_month_start", sql`period_month = (date_trunc('month'::text, (period_month)::timestamp with time zone))::date`),
]);

export const suburbStats = pgTable("suburb_stats", {
	suburbId: integer("suburb_id").notNull(),
	listingType: listingType("listing_type").notNull(),
	activeListingCount: integer("active_listing_count").default(0).notNull(),
	medianPrice: numeric("median_price", { precision: 14, scale:  2 }),
	avgPrice: numeric("avg_price", { precision: 14, scale:  2 }),
	minPrice: numeric("min_price", { precision: 14, scale:  2 }),
	maxPrice: numeric("max_price", { precision: 14, scale:  2 }),
	medianPricePerSqm: numeric("median_price_per_sqm", { precision: 12, scale:  2 }),
	lastCalculatedAt: timestamp("last_calculated_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
}, (table) => [
	index("idx_suburb_stats_listing_type").using("btree", table.listingType.asc().nullsLast().op("enum_ops")),
	foreignKey({
			columns: [table.suburbId],
			foreignColumns: [suburbs.id],
			name: "suburb_stats_suburb_id_fkey"
		}).onDelete("cascade"),
	primaryKey({ columns: [table.suburbId, table.listingType], name: "suburb_stats_pkey"}),
]);
