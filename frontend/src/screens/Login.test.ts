import { describe, expect, it } from "vitest";

import { LOGIN_ERRORS, validateLogin } from "./Login";

describe("validateLogin (the prototype's rules)", () => {
  it.each(["", "demo", "demo@", "demo@konboro", "de mo@konboro.local"])("bad email %j", (email) => {
    expect(validateLogin(email, "long-enough")).toEqual({ field: "email", message: LOGIN_ERRORS.email });
  });

  it("the email is checked before the password", () => {
    expect(validateLogin("x", "")?.field).toBe("email");
  });

  it("a password under 8 characters", () => {
    expect(validateLogin("demo@konboro.local", "1234567")).toEqual({
      field: "password",
      message: LOGIN_ERRORS.password,
    });
  });

  it("valid input", () => {
    expect(validateLogin("demo@konboro.local", "12345678")).toBeNull();
  });
});
