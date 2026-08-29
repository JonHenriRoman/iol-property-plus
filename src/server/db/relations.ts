import { relations } from "drizzle-orm/relations";
import { provinces, cities, suburbs, feedSources, importJobs, importErrors, agencies, agencyVendorIds, listings, enquiries, agents, users, agentVendorIds, developments, propertyTypes, listingRentalDetails, listingMedia, listingPriceHistory, savedSearches, listingFavourites, priceAlerts, agentReviews, suburbPriceMonthly, suburbStats } from "./schema";

export const citiesRelations = relations(cities, ({one, many}) => ({
	province: one(provinces, {
		fields: [cities.provinceId],
		references: [provinces.id]
	}),
	suburbs: many(suburbs),
}));

export const provincesRelations = relations(provinces, ({many}) => ({
	cities: many(cities),
}));

export const suburbsRelations = relations(suburbs, ({one, many}) => ({
	city: one(cities, {
		fields: [suburbs.cityId],
		references: [cities.id]
	}),
	agencies: many(agencies),
	developments: many(developments),
	listings: many(listings),
	suburbPriceMonthlies: many(suburbPriceMonthly),
	suburbStats: many(suburbStats),
}));

export const importJobsRelations = relations(importJobs, ({one, many}) => ({
	feedSource: one(feedSources, {
		fields: [importJobs.feedSourceId],
		references: [feedSources.id]
	}),
	importErrors: many(importErrors),
	listingPriceHistories: many(listingPriceHistory),
}));

export const feedSourcesRelations = relations(feedSources, ({many}) => ({
	importJobs: many(importJobs),
	importErrors: many(importErrors),
	agencyVendorIds: many(agencyVendorIds),
	agentVendorIds: many(agentVendorIds),
	listings: many(listings),
}));

export const importErrorsRelations = relations(importErrors, ({one}) => ({
	importJob: one(importJobs, {
		fields: [importErrors.importJobId],
		references: [importJobs.id]
	}),
	feedSource: one(feedSources, {
		fields: [importErrors.feedSourceId],
		references: [feedSources.id]
	}),
}));

export const agenciesRelations = relations(agencies, ({one, many}) => ({
	suburb: one(suburbs, {
		fields: [agencies.suburbId],
		references: [suburbs.id]
	}),
	agencyVendorIds: many(agencyVendorIds),
	enquiries: many(enquiries),
	agents: many(agents),
	listings: many(listings),
}));

export const agencyVendorIdsRelations = relations(agencyVendorIds, ({one}) => ({
	agency: one(agencies, {
		fields: [agencyVendorIds.agencyId],
		references: [agencies.id]
	}),
	feedSource: one(feedSources, {
		fields: [agencyVendorIds.feedSourceId],
		references: [feedSources.id]
	}),
}));

export const enquiriesRelations = relations(enquiries, ({one}) => ({
	listing: one(listings, {
		fields: [enquiries.listingId],
		references: [listings.id]
	}),
	agency: one(agencies, {
		fields: [enquiries.agencyId],
		references: [agencies.id]
	}),
	agent: one(agents, {
		fields: [enquiries.agentId],
		references: [agents.id]
	}),
	user: one(users, {
		fields: [enquiries.userId],
		references: [users.id]
	}),
}));

export const listingsRelations = relations(listings, ({one, many}) => ({
	enquiries: many(enquiries),
	propertyType: one(propertyTypes, {
		fields: [listings.propertyTypeId],
		references: [propertyTypes.id]
	}),
	suburb: one(suburbs, {
		fields: [listings.suburbId],
		references: [suburbs.id]
	}),
	feedSource: one(feedSources, {
		fields: [listings.feedSourceId],
		references: [feedSources.id]
	}),
	agency: one(agencies, {
		fields: [listings.agencyId],
		references: [agencies.id]
	}),
	agent: one(agents, {
		fields: [listings.agentId],
		references: [agents.id]
	}),
	development: one(developments, {
		fields: [listings.developmentId],
		references: [developments.id]
	}),
	listingRentalDetails: many(listingRentalDetails),
	listingMedias: many(listingMedia),
	listingPriceHistories: many(listingPriceHistory),
	listingFavourites: many(listingFavourites),
	priceAlerts: many(priceAlerts),
	agentReviews: many(agentReviews),
}));

export const agentsRelations = relations(agents, ({one, many}) => ({
	enquiries: many(enquiries),
	agency: one(agencies, {
		fields: [agents.agencyId],
		references: [agencies.id]
	}),
	agentVendorIds: many(agentVendorIds),
	listings: many(listings),
	agentReviews: many(agentReviews),
}));

export const usersRelations = relations(users, ({many}) => ({
	enquiries: many(enquiries),
	savedSearches: many(savedSearches),
	listingFavourites: many(listingFavourites),
	priceAlerts: many(priceAlerts),
	agentReviews: many(agentReviews),
}));

export const agentVendorIdsRelations = relations(agentVendorIds, ({one}) => ({
	agent: one(agents, {
		fields: [agentVendorIds.agentId],
		references: [agents.id]
	}),
	feedSource: one(feedSources, {
		fields: [agentVendorIds.feedSourceId],
		references: [feedSources.id]
	}),
}));

export const developmentsRelations = relations(developments, ({one, many}) => ({
	suburb: one(suburbs, {
		fields: [developments.suburbId],
		references: [suburbs.id]
	}),
	listings: many(listings),
}));

export const propertyTypesRelations = relations(propertyTypes, ({many}) => ({
	listings: many(listings),
	suburbPriceMonthlies: many(suburbPriceMonthly),
}));

export const listingRentalDetailsRelations = relations(listingRentalDetails, ({one}) => ({
	listing: one(listings, {
		fields: [listingRentalDetails.listingId],
		references: [listings.id]
	}),
}));

export const listingMediaRelations = relations(listingMedia, ({one}) => ({
	listing: one(listings, {
		fields: [listingMedia.listingId],
		references: [listings.id]
	}),
}));

export const listingPriceHistoryRelations = relations(listingPriceHistory, ({one}) => ({
	listing: one(listings, {
		fields: [listingPriceHistory.listingId],
		references: [listings.id]
	}),
	importJob: one(importJobs, {
		fields: [listingPriceHistory.importJobId],
		references: [importJobs.id]
	}),
}));

export const savedSearchesRelations = relations(savedSearches, ({one, many}) => ({
	user: one(users, {
		fields: [savedSearches.userId],
		references: [users.id]
	}),
	priceAlerts: many(priceAlerts),
}));

export const listingFavouritesRelations = relations(listingFavourites, ({one}) => ({
	user: one(users, {
		fields: [listingFavourites.userId],
		references: [users.id]
	}),
	listing: one(listings, {
		fields: [listingFavourites.listingId],
		references: [listings.id]
	}),
}));

export const priceAlertsRelations = relations(priceAlerts, ({one}) => ({
	user: one(users, {
		fields: [priceAlerts.userId],
		references: [users.id]
	}),
	savedSearch: one(savedSearches, {
		fields: [priceAlerts.savedSearchId],
		references: [savedSearches.id]
	}),
	listing: one(listings, {
		fields: [priceAlerts.listingId],
		references: [listings.id]
	}),
}));

export const agentReviewsRelations = relations(agentReviews, ({one}) => ({
	agent: one(agents, {
		fields: [agentReviews.agentId],
		references: [agents.id]
	}),
	user: one(users, {
		fields: [agentReviews.reviewerUserId],
		references: [users.id]
	}),
	listing: one(listings, {
		fields: [agentReviews.relatedListingId],
		references: [listings.id]
	}),
}));

export const suburbPriceMonthlyRelations = relations(suburbPriceMonthly, ({one}) => ({
	suburb: one(suburbs, {
		fields: [suburbPriceMonthly.suburbId],
		references: [suburbs.id]
	}),
	propertyType: one(propertyTypes, {
		fields: [suburbPriceMonthly.propertyTypeId],
		references: [propertyTypes.id]
	}),
}));

export const suburbStatsRelations = relations(suburbStats, ({one}) => ({
	suburb: one(suburbs, {
		fields: [suburbStats.suburbId],
		references: [suburbs.id]
	}),
}));