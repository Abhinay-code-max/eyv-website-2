// Single source of truth for traveler-count derivation and validation, shared
// between the planner form (TripPlannerPage) and its submit payload. adults/
// children/seniors are the only stored state - the total is always derived,
// never stored separately, so it can never drift out of sync with the form.

export function getTotalTravelers({ adults = 0, children = 0, seniors = 0 } = {}) {
  return adults + children + seniors;
}

export function validateTravelers({ adults, children, seniors } = {}) {
  const fields = { adults, children, seniors };
  for (const [name, value] of Object.entries(fields)) {
    if (!Number.isInteger(value) || value < 0) {
      return `${name} must be a whole number of 0 or more`;
    }
  }
  if (getTotalTravelers(fields) < 1) {
    return 'At least 1 traveler (adult, child, or senior) is required';
  }
  return null;
}
