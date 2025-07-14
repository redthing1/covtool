
# covtool

a multitool for manipulating coverage traces for dynamic analysis

primarily built around the standard-ish [DrCov](https://www.ayrx.me/drcov-file-format/) coverage trace format; but supports converting other, simpler trace formats.
also supports a [custom backwards-compatible extension](./doc/drcov_spec_hits_v2.md) to the DrCov format to track block hitcounts.

## features

+ a flagship tui for inspecting traces
+ view stats about coverage traces
+ perform queries (intersection, difference, etc.) on multiple traces
+ edit traces (rebase modules, adjust offsets)
+ lift simple formats to drcov (write your own coverage tools)

## install

```sh
uv tool install covtool
```

## coverage formats

### flagship: drcov (+hits)

this is either the standard DrCov format (any version), or the custom extension to support hitcounts.

### simple formats (lifted to drcov)

you can make a file that just outputs block traces in very simple formats (one entry per line).
these get auto-detected and can be converted to drcov using the `lift` tool:

+ **module+offset**: `boombox+3a06`  
+ **address**: `14000419c` or `0x14000419c`  
+ **address+hits**: `14000419c 24`

you can lift to the standard format by specifying module names and optionally base addresses:

```sh
covtool lift input.txt -o output.drcov -M module@base_addr
```
