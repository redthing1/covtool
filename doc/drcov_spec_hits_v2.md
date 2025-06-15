### **DrCov Code Coverage File Format Specification**

**Version:** 1.0
**Date:** 2023-10-27

### **Table of Contents**

1.  **Introduction**
    1.1. Purpose
    1.2. Scope
    1.3. Terminology and Conventions
2.  **Overall File Structure**
3.  **Section Specifications**
    3.1. File Header
    3.2. Module Table
    3.3. Basic Block (BB) Table
    3.4. (Optional) Hit Count Table
4.  **Compatibility and Implementation Notes**
    4.1. For Producers (Generating Files)
    4.2. For Consumers (Parsing Files)
5.  **Complete Example File**

---

### **1. Introduction**

#### **1.1. Purpose**

This document provides a comprehensive specification for the `.drcov` file format. This format is used to store code coverage data collected by Dynamic Binary Instrumentation (DBI) tools. Its primary purpose is to serve as an interchange format for coverage analysis and visualization tools.

#### **1.2. Scope**

This specification details the structure of a `.drcov` file, including the mandatory sections for basic block coverage and an optional extension for tracking basic block execution counts (hit counts). It covers known variations of the format to guide the implementation of compatible tools.

#### **1.3. Terminology and Conventions**

*   **Producer:** A tool that generates `.drcov` files (e.g., DynamoRIO, a Frida script).
*   **Consumer:** A tool that reads and parses `.drcov` files (e.g., Lighthouse).
*   **Basic Block (BB):** A sequence of instructions with exactly one entry point and one exit point.
*   **Text Encoding:** All text portions of the file are encoded in UTF-8. Newlines are represented by the line feed character (`\n`).
*   **Byte Order:** All multi-byte binary integer values are encoded in **little-endian** byte order.

### **2. Overall File Structure**

A `.drcov` file is a mixed text and binary file composed of several sections that must appear in the following order:

1.  **File Header (Required):** Two lines of text metadata.
2.  **Module Table (Required):** A text-based table describing loaded modules.
3.  **Basic Block Table (Required):** A text header followed by a binary data block listing executed basic blocks.
4.  **Hit Count Table (Optional):** A text header followed by a binary data block listing execution counts for each basic block. Its presence is conditional.

```
+--------------------------+
|      File Header         | (Text)
+--------------------------+
|      Module Table        | (Text)
+--------------------------+
|   Basic Block (BB) Table | (Text Header + Binary Data)
+--------------------------+
|   Hit Count Table        | (Optional, Text Header + Binary Data)
+--------------------------+
```

### **3. Section Specifications**

#### **3.1. File Header**

The file must begin with a two-line text header.

| Field | Format | Example | Description |
| :--- | :--- | :--- | :--- |
| **Version** | `DRCOV VERSION: <version>` | `DRCOV VERSION: 2` | The version of the file format specification. Version `2` is the modern, standard version. |
| **Flavor** | `DRCOV FLAVOR: <string>` | `DRCOV FLAVOR: drcov` | An arbitrary string describing the Producer. If the optional Hit Count Table is present, it is recommended to use the suffix `-hits` (e.g., `drcov-hits`). |

**Example:**
```
DRCOV VERSION: 2
DRCOV FLAVOR: drcov-hits
```

#### **3.2. Module Table**

This section defines the memory map of modules (executables and libraries) loaded during coverage collection.

##### **3.2.1. Module Table Header**

The table begins with a single header line identifying the format version and entry count. Two header formats exist:

*   **Legacy Format:** `Module Table: <count>` (e.g., `Module Table: 39`)
*   **Modern Format:** `Module Table: version <ver>, count <count>` (e.g., `Module Table: version 2, count 39`)

##### **3.2.2. Columns Definition**

Modern format tables (version 2 and later) must include a line defining the column layout. This line begins with `Columns: ` and lists comma-separated field names.

##### **3.2.3. Column Versions**

The set of columns varies by table version.

| Table Ver | DynamoRIO Ver | Platform | Column Format |
| :--- | :--- | :--- | :--- |
| **2** | v7.0.0-RC1 | Windows | `id, base, end, entry, checksum, timestamp, path` |
| | | Mac/Linux | `id, base, end, entry, path` |
| **3** | v7.0.17594B | Windows | `id, containing_id, start, end, entry, checksum, timestamp, path` |
| | | Mac/Linux | `id, containing_id, start, end, entry, path` |
| **4** | v7.0.17640 | Windows | `id, containing_id, start, end, entry, offset, checksum, timestamp, path` |
| | | Mac/Linux | `id, containing_id, start, end, entry, offset, path` |

##### **3.2.4. Field Definitions**

| Field | Type | Essential? | Description |
| :--- | :--- | :--- | :--- |
| **`id`** | Integer | **Yes** | A zero-based, sequential ID for the module. |
| **`base`** or **`start`** | Hex Int | **Yes** | The base memory address where the module is loaded. |
| **`end`** | Hex Int | **Yes** | The memory address marking the end of the module's range. |
| **`path`** | String | **Yes** | The absolute file path of the module on disk. |
| `entry` | Hex Int | No | The module's entry point address. Can be `0`. |
| `checksum` | Hex Int | No | The file checksum. Can be `0`. |
| `timestamp` | Hex Int | No | The file timestamp. Can be `0`. |
| `containing_id` | Integer | No | Used for modules with multiple segments. |
| `offset` | Hex Int | No | File offset for the module's memory mapping. |

##### **3.2.5. Example**
```
Module Table: version 2, count 2
Columns: id, base, end, entry, path
 0, 0x10a2c3000, 0x10a2c4fff, 0x00000000, /path/to/my_program
 1, 0x7fff2030f000, 0x7fff204f0fff, 0x00000000, /usr/lib/dyld
```

#### **3.3. Basic Block (BB) Table**

This section lists every unique basic block executed during the run.

##### **3.3.1. Header**

This section starts with a single text line indicating the number of binary entries.

*   **Format:** `BB Table: <count> bbs`
*   **Example:** `BB Table: 861 bbs`

##### **3.3.2. Binary Data Format**

Following the header is a tightly packed binary array of `_bb_entry_t` structures. Each structure is **8 bytes**.

The C-style structure is defined as:
```c
typedef struct _bb_entry_t {
    uint32_t start;      // 4 bytes, little-endian
    uint16_t size;       // 2 bytes, little-endian
    uint16_t mod_id;     // 2 bytes, little-endian
} bb_entry_t;
```

| Field | Size (bytes) | Type | Description |
| :--- | :--- | :--- | :--- |
| **`start`** | 4 | `uint32_t` | The offset of the basic block's start address, relative to its module's base address. |
| **`size`** | 2 | `uint16_t` | The size of the basic block in bytes. |
| **`mod_id`** | 2 | `uint16_t` | The `id` of the module this block belongs to, referencing the Module Table. |

The absolute address of a basic block is calculated as: `ModuleTable[mod_id].base + start`.

#### **3.4. (Optional) Hit Count Table**

This optional section provides execution counts for each corresponding entry in the Basic Block Table.

##### **3.4.1. Detection**

A Consumer should look for this table after parsing the entire Basic Block Table. Its presence can be hinted by `DRCOV FLAVOR: drcov-hits` in the File Header, but a robust parser should attempt to read the next line regardless to check for the table's header.

##### **3.4.2. Header**

If present, the section begins with a single text line.

*   **Format:** `Hit Count Table: version <ver>, count <count>`
*   **Example:** `Hit Count Table: version 1, count 861`
*   **Validation:** The `count` in this header **must** be identical to the `count` in the `BB Table` header.

##### **3.4.3. Binary Data Format**

Following the header is a tightly packed binary array of hit counters.

*   **Data Type:** `uint32_t` (4 bytes, little-endian)
*   **Mapping:** This is a **parallel array** to the Basic Block Table. The Nth `uint32_t` in this section is the hit count for the Nth `_bb_entry_t` in the Basic Block Table.

### **4. Compatibility and Implementation Notes**

#### **4.1. For Producers (Generating Files)**

*   **Maximize Compatibility:** Generate `DRCOV VERSION: 2` files with a `Module Table: version 2`. This is the most widely supported modern format.
*   **Populate Essential Fields:** `id`, `base`/`start`, `end`, and `path` must be accurate. Other fields can be populated with `0`.
*   **Hit Count Extension:** If generating hit counts, use the `drcov-hits` flavor and ensure the `Hit Count Table` count matches the `BB Table` count.

#### **4.2. For Consumers (Parsing Files)**

*   **Be Flexible with Headers:** Be prepared to parse both legacy (`Module Table: <N>`) and modern (`Module Table: version X, count <N>`) headers.
*   **Parse Columns Dynamically:** Do not assume a fixed column order in the Module Table. Read the `Columns:` line and map field names to their index.
*   **Handle Optional Sections:** After successfully parsing the BB Table, attempt to read the next line to check for a `Hit Count Table` header. If it's not present, or if the `DRCOV FLAVOR` doesn't suggest it, you can safely assume the file ends there.
*   **Validate Counts:** If a `Hit Count Table` is found, validate that its entry count matches the `BB Table`'s entry count before proceeding.

### **5. Complete Example File**

This example demonstrates a complete `.drcov` file that includes the optional hit count extension.

```
DRCOV VERSION: 2
DRCOV FLAVOR: mytool-drcov-hits

Module Table: version 2, count 1
Columns: id, base, end, entry, path
 0, 0x400000, 0x401fff, 0x0, /home/user/my_app

BB Table: 3 bbs
# Binary Data (3 entries * 8 bytes/entry = 24 bytes) follows this line.
# Conceptually, the data represents:
# 1. _bb_entry_t { start: 0x1100, size: 10, mod_id: 0 }  (Address 0x401100)
# 2. _bb_entry_t { start: 0x110a, size: 5,  mod_id: 0 }  (Address 0x40110a)
# 3. _bb_entry_t { start: 0x110f, size: 22, mod_id: 0 }  (Address 0x40110f)

Hit Count Table: version 1, count 3
# Binary Data (3 entries * 4 bytes/entry = 12 bytes) follows this line.
# This data is a parallel array to the BB Table entries above.
# Conceptually, the data represents:
# 1. uint32_t: 1        (Hit count for BB at 0x401100)
# 2. uint32_t: 150      (Hit count for BB at 0x40110a)
# 3. uint32_t: 149      (Hit count for BB at 0x40110f)
```