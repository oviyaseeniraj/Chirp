#ifndef UTILITY_H
#define UTILITY_H

#include <string>
#include <iostream>
#include <fstream>
#include <vector>

/**
 * @brief Exports data to a binary file.
 * 
 * @tparam T Type of the data elements.
 * @param filename Path to the output file.
 * @param data Pointer to the data array.
 * @param length Number of elements to write.
 * @return int 0 on success, -1 on failure.
 */
template <typename T>
int export_to_binary(const std::string& filename, const T* data, size_t length) {
    std::ofstream outfile(filename, std::ios::binary);
    if (!outfile.is_open()) {
        std::cerr << "[ERROR] Could not open file for writing: " << filename << std::endl;
        return -1;
    }

    outfile.write(reinterpret_cast<const char*>(data), length * sizeof(T));
    outfile.close();
    return 0;
}

/**
 * @brief Imports data from a binary file.
 * 
 * @tparam T Type of the data elements.
 * @param filename Path to the input file.
 * @param data Pointer to the pre-allocated array where data will be stored.
 * @param length Number of elements to read.
 * @return int 0 on success, -1 on failure.
 */
template <typename T>
int import_from_binary(const std::string& filename, T* data, size_t length) {
    std::ifstream infile(filename, std::ios::binary);
    if (!infile.is_open()) {
        std::cerr << "[ERROR] Could not open file for reading: " << filename << std::endl;
        return -1;
    }

    infile.read(reinterpret_cast<char*>(data), length * sizeof(T));

    if (!infile) {
        std::cerr << "[ERROR] Only read " << infile.gcount() << " bytes from " << filename << std::endl;
        return -1;
    }

    infile.close();
    return 0;
}

#endif // UTILITY_H
