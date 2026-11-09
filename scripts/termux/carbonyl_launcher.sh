#!/system/bin/sh
libdir=/data/data/com.terminal.nextgen/files/usr/lib/carbonyl
export LD_PRELOAD="$libdir/libtermi-carbonyl-exe.so${LD_PRELOAD:+:$LD_PRELOAD}"
exec /system/bin/linker64 "$libdir/headless_shell" \
    --no-zygote "--browser-subprocess-path=$libdir/headless_shell" "$@"
