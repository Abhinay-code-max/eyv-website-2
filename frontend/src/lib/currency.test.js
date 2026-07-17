import { getCurrencySymbol, formatCurrency } from './currency';

describe('getCurrencySymbol', () => {
  test('INR => ₹', () => {
    expect(getCurrencySymbol('INR')).toBe('₹');
  });

  test('lowercase inr => ₹ (case-insensitive)', () => {
    expect(getCurrencySymbol('inr')).toBe('₹');
  });

  test('USD => $', () => {
    expect(getCurrencySymbol('USD')).toBe('$');
  });

  test('EUR => €', () => {
    expect(getCurrencySymbol('EUR')).toBe('€');
  });

  test('GBP => £', () => {
    expect(getCurrencySymbol('GBP')).toBe('£');
  });

  test('missing currency code does not fall back to $', () => {
    const warn = jest.spyOn(console, 'warn').mockImplementation(() => {});
    expect(getCurrencySymbol(undefined)).toBe('');
    expect(getCurrencySymbol(null)).toBe('');
    expect(getCurrencySymbol('')).toBe('');
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });

  test('unrecognized currency code shows the code, not a guessed symbol', () => {
    const warn = jest.spyOn(console, 'warn').mockImplementation(() => {});
    expect(getCurrencySymbol('XYZ')).toBe('XYZ ');
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});

describe('formatCurrency', () => {
  test('INR uses Indian digit grouping', () => {
    expect(formatCurrency(182397, 'INR')).toBe('₹1,82,397');
  });

  test('INR with cents/paise', () => {
    expect(formatCurrency(963.07, 'INR')).toBe('₹963.07');
  });

  test('USD uses standard international grouping, not Indian grouping', () => {
    expect(formatCurrency(9543.97, 'USD')).toBe('$9,543.97');
  });

  test('missing amount defaults to 0, not NaN', () => {
    expect(formatCurrency(undefined, 'INR')).toBe('₹0');
  });

  test('missing currency does not silently show $', () => {
    const warn = jest.spyOn(console, 'warn').mockImplementation(() => {});
    expect(formatCurrency(100, undefined)).toBe('100');
    warn.mockRestore();
  });
});
