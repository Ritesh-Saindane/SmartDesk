// mergesort.cpp
// Implementation of Merge Sort algorithm in C++
// Demonstrates sorting an example array.

#include <iostream>
#include <vector>

// Function to merge two sorted subarrays
// arr[left..mid] and arr[mid+1..right]
void merge(std::vector<int>& arr, int left, int mid, int right) {
    int n1 = mid - left + 1; // size of left subarray
    int n2 = right - mid;    // size of right subarray

    // Create temporary vectors
    std::vector<int> L(n1);
    std::vector<int> R(n2);

    // Copy data to temporary vectors L and R
    for (int i = 0; i < n1; ++i)
        L[i] = arr[left + i];
    for (int j = 0; j < n2; ++j)
        R[j] = arr[mid + 1 + j];

    // Merge the temporary vectors back into arr[left..right]
    int i = 0; // Initial index of left subarray
    int j = 0; // Initial index of right subarray
    int k = left; // Initial index of merged subarray

    while (i < n1 && j < n2) {
        if (L[i] <= R[j]) {
            arr[k] = L[i];
            ++i;
        } else {
            arr[k] = R[j];
            ++j;
        }
        ++k;
    }

    // Copy any remaining elements of L, if there are any
    while (i < n1) {
        arr[k] = L[i];
        ++i;
        ++k;
    }

    // Copy any remaining elements of R, if there are any
    while (j < n2) {
        arr[k] = R[j];
        ++j;
        ++k;
    }
}

// Recursive merge sort function
void mergeSort(std::vector<int>& arr, int left, int right) {
    if (left < right) {
        int mid = left + (right - left) / 2; // Avoid overflow
        // Sort first and second halves
        mergeSort(arr, left, mid);
        mergeSort(arr, mid + 1, right);
        // Merge the sorted halves
        merge(arr, left, mid, right);
    }
}

int main() {
    // Example array to sort
    std::vector<int> data = {38, 27, 43, 3, 9, 82, 10};

    std::cout << "Original array: ";
    for (int val : data) {
        std::cout << val << " ";
    }
    std::cout << std::endl;

    // Perform merge sort
    mergeSort(data, 0, static_cast<int>(data.size()) - 1);

    std::cout << "Sorted array:   ";
    for (int val : data) {
        std::cout << val << " ";
    }
    std::cout << std::endl;

    return 0;
}
