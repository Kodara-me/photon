# Photon development slices

Complete these slices in order. Each slice should produce a small observable result and should be independently reviewable. Do not skip hardware verification by copying assumed report bytes from another device.

The first seven slices are intentionally focused on the G733 and form the first milestone. Slices 8–10 add the other Logitech devices. Slices 11–15 add only the minimum shared code and event-driven service behavior. Slice 16 adds the exact Corsair Vengeance RGB DDR5 backend.

Each slice document specifies scope, non-goals, verification, and definition of done. Slice 17 adds the installed root system service after the device-control slices.

17. [Root system service](17-root-system-service.md)
18. [Standalone fan RGB experiment](18-fan-rgb-test.md)
19. [Motherboard/fan RGB in the service](19-motherboard-rgb-service.md)
20. [Windows service and reconnect monitoring](20-windows-service.md)
