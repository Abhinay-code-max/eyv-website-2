// Single source of truth for rendering a currency code (e.g. "INR", "usd")
// as a symbol and a formatted amount, shared across every page that
// displays a price. Never silently falls back to a hardcoded symbol - a
// missing or unrecognized currency code fails visibly (console warning,
// and the raw code shown as text instead of a guessed symbol) so a data
// gap is obvious rather than quietly rendering the wrong currency.

const CURRENCY_SYMBOLS = {
  INR: '₹',
  USD: '$',
  EUR: '€',
  GBP: '£',
  AED: 'AED ',
  SGD: 'S$',
  AUD: 'A$',
  JPY: '¥',
};

export function getCurrencySymbol(currencyCode) {
  if (!currencyCode) {
    console.warn('getCurrencySymbol: missing currency code - rendering without a symbol');
    return '';
  }
  const code = String(currencyCode).toUpperCase();
  const symbol = CURRENCY_SYMBOLS[code];
  if (!symbol) {
    console.warn(`getCurrencySymbol: unrecognized currency code "${currencyCode}" - showing the code instead of guessing a symbol`);
    return `${code} `;
  }
  return symbol;
}

// INR conventionally groups digits differently (lakh/crore, e.g. 1,00,000)
// than USD/EUR/etc - forcing one currency's grouping onto another looks
// visibly wrong, so the locale used for grouping follows the currency.
function _localeFor(currencyCode) {
  return String(currencyCode || '').toUpperCase() === 'INR' ? 'en-IN' : 'en-US';
}

// Just the grouped number, no symbol - for layouts that render the symbol
// and amount as separately styled elements rather than one string.
export function formatNumber(amount, currencyCode) {
  return Number(amount ?? 0).toLocaleString(_localeFor(currencyCode));
}

export function formatCurrency(amount, currencyCode) {
  return `${getCurrencySymbol(currencyCode)}${formatNumber(amount, currencyCode)}`;
}
