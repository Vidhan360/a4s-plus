import { describe, expect, it } from 'vitest';

import { ApiError, errorMessage } from '@/lib/api-error';

describe('ApiError', () => {
  it('flags forbidden responses so panels can explain RBAC instead of failing', () => {
    const error = new ApiError(403, 'forbidden', 'Missing permission alert:resolve');
    expect(error.isForbidden).toBe(true);
    expect(error.isUnauthorised).toBe(false);
  });

  it('flags unauthorised responses separately from forbidden ones', () => {
    const error = new ApiError(401, 'unauthorized', 'Token expired');
    expect(error.isUnauthorised).toBe(true);
    expect(error.isForbidden).toBe(false);
  });

  it('extracts normalised 422 field errors into a per-field map', () => {
    // The backend's validation handler flattens Pydantic's `loc`/`msg` into
    // `{field, message, type}`; this asserts the client reads that shape.
    const error = new ApiError(422, 'validation_error', 'Invalid payload', [
      { field: 'heart_rate', message: 'Input should be greater than 0', type: 'greater_than' },
      { field: 'spo2', message: 'Input should be less than or equal to 100', type: 'less_than' },
    ]);
    expect(error.fieldErrors).toEqual({
      heart_rate: 'Input should be greater than 0',
      spo2: 'Input should be less than or equal to 100',
    });
  });

  it('returns an empty field map when details are not a validation list', () => {
    expect(new ApiError(500, 'server_error', 'boom').fieldErrors).toEqual({});
  });
});

describe('errorMessage', () => {
  it('prefers the API-supplied message', () => {
    expect(errorMessage(new ApiError(409, 'conflict', 'Call sign already exists'))).toBe(
      'Call sign already exists',
    );
  });

  it('handles plain errors and unknown throwables', () => {
    expect(errorMessage(new Error('network down'))).toBe('network down');
    expect(errorMessage('weird')).toBeTypeOf('string');
    expect(errorMessage(undefined)).toBeTypeOf('string');
  });
});
