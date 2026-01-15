#ifndef RANGE_DOPPLER_H
#define RANGE_DOPPLER_H

#include "main.h"
#include "RadarBlock.h"
#include <eigen3/Eigen/Dense>
#include <fftw3.h>


class RangeDoppler : public RadarBlock
{
    public:
        RangeDoppler(const char *win = "blackman");

        void remove_zero_dop(float *rdm_avg, float *zero_rdm_avg);

        int compute_angle_est();

        int compute_angmag_norm(std::complex<float> *rdm_complex, float *rdm_magnitude);

        void find_azimuth_angle(float *angle_norm, float *final_angle);

        void correlation_matrix(float *rdm_avg, float *prev_rdm_avg, float *cfar_cube, std::complex<float> *adc_data, int *cfar_max, std::complex<float> *Rmatrix, float *final_range, float *final_angle);

        void output_energy(std::complex<float> *Rmatrix, int *cfar_max, float *final_angle);

        Eigen::Matrix<std::complex<float>, 12, 1> steering_mat(int angle);

        void getADCaverage(int index_1D, std::complex<float> *xnvalues, std::complex<float> *adc_data);

        float *getRangeBufferPointer();

        float *getAngleBufferPointer();

        int *getAngleIndexPointer();

        // Still need to fix this fftshift issue (we think this means that Percept's angle estimation never worked)
        void fftshift_ang_est(float *arr);

        int cfar_matrix(float *rdm_avg, float *prev_rdm_avg, float *cfar_cube);

        void getADCindices(int index_1D, int *indices);

        float mean_noise_rdm(float *rdm_avg);

        void shape_angle_data(float *rdm_avg, float *prev_rdm_avg, float *cfar_cube, std::complex<float> *adc_data, std::complex<float> *angle_data, int *cfar_max);

        // Retrieve outputbuffer pointer
        float *getBufferPointer();

        void setBufferPointer(uint16_t *arr);

        // FILE READING METHODS
        void readFile(const std::string &filename);

        int save_1d_array(float *arr, int width, int length, std::string &filename);

        // WINDOW TYPES
        void blackman_window(float *arr, int fast_time);

        void hann_window(float *arr, int fast_time);

        void no_window(float *arr, int fast_time);

        void setSNR(float maxSNR, float minSNR);

        // output indices --> {IQ, FAST_TIME, SLOW_TIME, RX, TX}
        void getIndices(int index_1D, int *indices);

        /*
        * shape_cube() reformats the radar cube, which is a 5D matrix
        * 'in' has an order like this: frame[Chirp Loop][TX][Sample #][IQ][RX]
        * 'mid' has an order like this: frame[TX][RX][Chirp Loop][Sample #][IQ]
        * TODO: what is the difference between 'mid' and 'out' then? 
        */
        void shape_cube(float *in, float *mid, std::complex<float> *out);

        int compute_range_doppler();

        void scale_rdm_values(float *arr, float max_val, float min_val);

        void fftshift_rdm(float *arr);

        int compute_mag_norm(std::complex<float> *rdm_complex, float *rdm_magnitude);

        // rdm_avg should be zero-filled
        int averaged_rdm(float *rdm_norm, float *rdm_avg);

        void process() override;

    private:
        float *adc_data_flat, *rdm_avg, *rdm_norm, *adc_data_reshaped, *cfar_cube, *angle_norm, *final_angle, *final_range, *prev_rdm_avg, *zero_rdm_avg;
        std::complex<float> *rdm_data, *adc_data, *angle_data, *angfft_data, *Rmatrix;
        fftwf_plan plan, plan2;
        int *cfar_max;
        uint16_t *input;
        const char *WINDOW_TYPE;
        bool SET_SNR;
        float max, min;
};

#endif