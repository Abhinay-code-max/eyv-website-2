import { getTotalTravelers, validateTravelers } from './travelers';

describe('getTotalTravelers', () => {
  test('adults=2 children=2 seniors=1 => 5', () => {
    expect(getTotalTravelers({ adults: 2, children: 2, seniors: 1 })).toBe(5);
  });

  test('adults=2 children=0 seniors=0 => 2', () => {
    expect(getTotalTravelers({ adults: 2, children: 0, seniors: 0 })).toBe(2);
  });

  test('adults=0 children=0 seniors=3 => 3', () => {
    expect(getTotalTravelers({ adults: 0, children: 0, seniors: 3 })).toBe(3);
  });

  test('adults=0 children=0 seniors=0 => 0', () => {
    expect(getTotalTravelers({ adults: 0, children: 0, seniors: 0 })).toBe(0);
  });
});

describe('validateTravelers', () => {
  test('valid mixed group passes', () => {
    expect(validateTravelers({ adults: 2, children: 2, seniors: 1 })).toBeNull();
  });

  test('valid adults-only group passes', () => {
    expect(validateTravelers({ adults: 2, children: 0, seniors: 0 })).toBeNull();
  });

  test('valid seniors-only group passes', () => {
    expect(validateTravelers({ adults: 0, children: 0, seniors: 3 })).toBeNull();
  });

  test('all zero fails validation', () => {
    expect(validateTravelers({ adults: 0, children: 0, seniors: 0 })).not.toBeNull();
  });

  test('negative value fails validation', () => {
    expect(validateTravelers({ adults: -1, children: 0, seniors: 0 })).not.toBeNull();
  });

  test('decimal value fails validation', () => {
    expect(validateTravelers({ adults: 2.5, children: 0, seniors: 0 })).not.toBeNull();
  });

  test('NaN value fails validation', () => {
    expect(validateTravelers({ adults: NaN, children: 0, seniors: 0 })).not.toBeNull();
  });

  test('undefined value fails validation', () => {
    expect(validateTravelers({ adults: undefined, children: 0, seniors: 0 })).not.toBeNull();
  });

  test('null value fails validation', () => {
    expect(validateTravelers({ adults: null, children: 0, seniors: 0 })).not.toBeNull();
  });
});
