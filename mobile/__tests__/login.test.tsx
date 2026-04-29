/**
 * Smoke test: the login screen renders without crashing and shows the
 * expected title + form controls. This is the only render test required
 * for Phase 0 — full E2E (Detox) is Phase 2.
 */

import { render } from '@testing-library/react-native';
import LoginScreen from '../app/(auth)/login';

// expo-router's `router` is a side-effecty native module; mock it so the
// login screen import doesn't try to register routes during a unit test.
jest.mock('expo-router', () => ({
  router: { replace: jest.fn(), push: jest.fn() },
  Stack: () => null,
  Tabs: () => null,
  Redirect: () => null,
  useLocalSearchParams: () => ({}),
}));

jest.mock('expo-secure-store', () => ({
  getItemAsync: jest.fn(async () => null),
  setItemAsync: jest.fn(async () => undefined),
  deleteItemAsync: jest.fn(async () => undefined),
}));

jest.mock('expo-constants', () => ({
  default: { expoConfig: { extra: { apiBaseUrl: 'http://localhost:8000' } } },
  expoConfig: { extra: { apiBaseUrl: 'http://localhost:8000' } },
}));

describe('LoginScreen', () => {
  it('renders the title, email/password inputs, and submit button', () => {
    const { getByText, getByTestId } = render(<LoginScreen />);
    expect(getByText('YieldIQ')).toBeTruthy();
    expect(getByText('Sign in to your account')).toBeTruthy();
    expect(getByTestId('login-email')).toBeTruthy();
    expect(getByTestId('login-password')).toBeTruthy();
    expect(getByTestId('login-submit')).toBeTruthy();
  });
});
