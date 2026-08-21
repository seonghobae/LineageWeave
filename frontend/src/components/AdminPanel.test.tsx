import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AdminPanel } from "./AdminPanel";

afterEach(() => vi.unstubAllGlobals());

describe("AdminPanel", () => {
  const baseProps = {
    currentTenantConfig: {
      brandName: "LineageWeave",
      systemName: "LineageWeave Intelligence",
      copyrightYear: 2026,
      copyrightHolder: "LineageWeave",
    },
    onTenantConfigChange: vi.fn(),
    accessToken: "access-token",
    onNavigate: vi.fn(),
    onOpenBoardTool: vi.fn(),
  };

  it("organizes admin routes into an accessible LNB", () => {
    render(<AdminPanel {...baseProps} />);

    expect(screen.getByRole("navigation", { name: "Admin navigation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Post evidence operations/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Lineage rebuild/ })).toBeInTheDocument();
    expect(screen.getByText("10 routes")).toBeInTheDocument();
    expect(screen.getByText("POST /api/lineage/rebuild")).toBeInTheDocument();
  });

  it("hands existing workspace surfaces to their real destination", () => {
    const onNavigate = vi.fn();
    const onOpenBoardTool = vi.fn();
    render(<AdminPanel {...baseProps} onNavigate={onNavigate} onOpenBoardTool={onOpenBoardTool} />);

    fireEvent.click(within(screen.getByRole("navigation", { name: "Admin navigation" })).getByRole("button", { name: /Board & posts/ }));
    expect(onNavigate).toHaveBeenCalledWith("board");

    fireEvent.click(screen.getByRole("button", { name: /Period reports/ }));
    expect(onOpenBoardTool).toHaveBeenCalledWith("reports");
  });

  it("keeps tenant settings in the admin surface", () => {
    render(<AdminPanel {...baseProps} />);

    fireEvent.click(screen.getByRole("button", { name: /Tenant settings/ }));
    expect(screen.getByRole("heading", { name: "Tenant settings" })).toBeInTheDocument();
    const brandInput = screen.getByRole("textbox", { name: "Tenant brand name" });
    expect(brandInput).toHaveValue("LineageWeave");
    // The visible "*" is decorative (aria-hidden); a screen reader must
    // still hear this field is required, which only the required attribute
    // guarantees regardless of how the accessible name was computed.
    expect(brandInput).toBeRequired();
    expect(screen.getByRole("textbox", { name: "Tenant system name" })).toHaveValue("LineageWeave Intelligence");
    expect(screen.getByRole("textbox", { name: "Tenant copyright holder" })).toHaveValue("LineageWeave");
    expect(screen.getByRole("spinbutton", { name: "Tenant copyright year" })).toHaveValue(2026);
  });

  it("saves the complete identity metadata contract", async () => {
    const onTenantConfigChange = vi.fn();
    const responseConfig = {
      brandName: "Example Brand",
      systemName: "Example System",
      copyrightYear: 2025,
      copyrightHolder: "Example Rights Holder",
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(responseConfig), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<AdminPanel {...baseProps} onTenantConfigChange={onTenantConfigChange} />);
    fireEvent.click(screen.getByRole("button", { name: /Tenant settings/ }));
    fireEvent.change(screen.getByRole("textbox", { name: "Tenant brand name" }), {
      target: { value: responseConfig.brandName },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Tenant system name" }), {
      target: { value: responseConfig.systemName },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Tenant copyright holder" }), {
      target: { value: responseConfig.copyrightHolder },
    });
    fireEvent.change(screen.getByRole("spinbutton", { name: "Tenant copyright year" }), {
      target: { value: String(responseConfig.copyrightYear) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save settings" }));

    await waitFor(() => expect(onTenantConfigChange).toHaveBeenCalledWith(responseConfig));
    const request = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/api/settings"));
    expect(JSON.parse(String(request?.[1]?.body))).toEqual(responseConfig);
  });

  it("rejects a copyright year outside the approved range in the submit handler", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(<AdminPanel {...baseProps} />);
    fireEvent.click(screen.getByRole("button", { name: /Tenant settings/ }));
    fireEvent.change(screen.getByRole("spinbutton", { name: "Tenant copyright year" }), {
      target: { value: "1899" },
    });

    const saveButton = screen.getByRole("button", { name: "Save settings" });
    expect(saveButton).toBeDisabled();
    fireEvent.submit(saveButton.closest("form")!);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("keeps a cleared copyright year visibly blank while editing", () => {
    render(<AdminPanel {...baseProps} />);
    fireEvent.click(screen.getByRole("button", { name: /Tenant settings/ }));
    const yearInput = screen.getByRole("spinbutton", { name: "Tenant copyright year" });

    fireEvent.change(yearInput, { target: { value: "" } });

    expect(yearInput).toHaveValue(null);
    expect(screen.getByRole("button", { name: "Save settings" })).toBeDisabled();
  });

  it("does not submit unchanged settings through the form", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(<AdminPanel {...baseProps} />);
    fireEvent.click(screen.getByRole("button", { name: /Tenant settings/ }));
    fireEvent.submit(screen.getByRole("button", { name: "Save settings" }).closest("form")!);

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("refreshes the draft when the fetched tenant config arrives", () => {
    const { rerender } = render(<AdminPanel {...baseProps} />);

    fireEvent.click(screen.getByRole("button", { name: /Tenant settings/ }));
    rerender(
      <AdminPanel
        {...baseProps}
        currentTenantConfig={{
          brandName: "Fetched Brand",
          systemName: "Fetched System",
          copyrightYear: 2025,
          copyrightHolder: "Fetched Rights Holder",
        }}
      />,
    );

    expect(screen.getByRole("textbox", { name: "Tenant brand name" })).toHaveValue("Fetched Brand");
    expect(screen.getByRole("textbox", { name: "Tenant system name" })).toHaveValue("Fetched System");
    expect(screen.getByRole("spinbutton", { name: "Tenant copyright year" })).toHaveValue(2025);
    expect(screen.getByRole("textbox", { name: "Tenant copyright holder" })).toHaveValue("Fetched Rights Holder");
  });

  it("preserves edited fields when the fetched tenant config arrives", () => {
    const { rerender } = render(<AdminPanel {...baseProps} />);

    fireEvent.click(screen.getByRole("button", { name: /Tenant settings/ }));
    fireEvent.change(screen.getByRole("textbox", { name: "Tenant brand name" }), {
      target: { value: "Draft Brand" },
    });
    rerender(
      <AdminPanel
        {...baseProps}
        currentTenantConfig={{
          brandName: "Fetched Brand",
          systemName: "Fetched System",
          copyrightYear: 2025,
          copyrightHolder: "Fetched Rights Holder",
        }}
      />,
    );

    expect(screen.getByRole("textbox", { name: "Tenant brand name" })).toHaveValue("Draft Brand");
    expect(screen.getByRole("textbox", { name: "Tenant system name" })).toHaveValue("Fetched System");
    expect(screen.getByRole("spinbutton", { name: "Tenant copyright year" })).toHaveValue(2025);
    expect(screen.getByRole("textbox", { name: "Tenant copyright holder" })).toHaveValue("Fetched Rights Holder");
  });

});
