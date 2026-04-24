#include "RangeDoppler.h"
#include "RadarBlock.h"
#include "main.h"

#include <fftw3.h>
#include <algorithm>

RangeDoppler::RangeDoppler(const char *win) : RadarBlock(SIZE, SIZE)
{
    // RANGE DOPPLER PARAMETER INITIALIZATION
    WINDOW_TYPE = win; // Determines what type of windowing will be done
    SET_SNR = false;
    adc_data_flat = reinterpret_cast<float *>(malloc(SIZE_W_IQ * sizeof(float)));                   // allocate mem for Separate IQ adc data from Data aquisition
    adc_data = reinterpret_cast<std::complex<float> *>(adc_data_flat);                              // allocate mem for COMPLEX adc data from Data aquisition
    adc_data_reshaped = reinterpret_cast<float *>(malloc(SIZE_W_IQ * sizeof(float)));               // allocate mem for reorganized/reshaped adc data
    rdm_data = reinterpret_cast<std::complex<float> *>(malloc(SIZE * sizeof(std::complex<float>))); // allocate mem for processed complex adc data
    rdm_norm = reinterpret_cast<float *>(malloc(SIZE * sizeof(float)));                             // allocate mem for processed magnitude adc data
    rdm_avg = reinterpret_cast<float *>(calloc(SLOW_TIME * FAST_TIME, sizeof(float)));              // allocate mem for averaged adc data across all virtual antennas
    prev_rdm_avg = reinterpret_cast<float *>(calloc(SLOW_TIME * FAST_TIME, sizeof(float)));         // Previous frame allocation
    zero_rdm_avg = reinterpret_cast<float *>(calloc(SLOW_TIME * FAST_TIME, sizeof(float)));         // rdm avg but with 0 doppler removed

    cfar_cube = reinterpret_cast<float *>(calloc(SLOW_TIME * FAST_TIME, sizeof(float)));
    angle_data = reinterpret_cast<std::complex<float> *>(calloc(96, sizeof(std::complex<float>)));
    angfft_data = reinterpret_cast<std::complex<float> *>(calloc(96, sizeof(std::complex<float>)));
    angle_norm = reinterpret_cast<float *>(malloc(96 * sizeof(float)));
    final_angle = reinterpret_cast<float *>(malloc(1 * sizeof(float)));
    final_range = reinterpret_cast<float *>(malloc(1 * sizeof(float)));
    cfar_max = reinterpret_cast<int *>(malloc(1 * sizeof(int)));
    final_doppler = reinterpret_cast<float*>(malloc(1 * sizeof(float)));
    final_doppler_bin = reinterpret_cast<int*>(malloc(1 * sizeof(int)));
    // Rmatrix = reinterpret_cast<std::complex<float>*>(malloc(64 * sizeof(std::complex<float>)));
    Rmatrix = reinterpret_cast<std::complex<float> *>(malloc(144 * sizeof(std::complex<float>)));

    // FFT SETUP PARAMETERS
    const int rank = 2; // Determines the # of dimensions for FFT
    const int n[] = {SLOW_TIME, FAST_TIME};
    const int howmany = TX * RX;
    const int idist = SLOW_TIME * FAST_TIME;
    const int odist = SLOW_TIME * FAST_TIME;
    const int istride = 1;
    const int ostride = 1;
    plan = fftwf_plan_many_dft(rank, n, howmany,
                               reinterpret_cast<fftwf_complex *>(adc_data), n, istride, idist,
                               reinterpret_cast<fftwf_complex *>(rdm_data), n, ostride, odist,
                               FFTW_FORWARD, FFTW_ESTIMATE); // create the FFT plan

    const int rank2 = 2; // Determines the # of dimensions for FFT
    const int n2[] = {6, 16};
    const int howmany2 = 1;
    const int idist2 = 0;
    const int odist2 = 0;
    const int istride2 = 1;
    const int ostride2 = 1;
    plan2 = fftwf_plan_many_dft(rank2, n2, howmany2,
                                reinterpret_cast<fftwf_complex *>(angle_data), n2, istride2, idist2,
                                reinterpret_cast<fftwf_complex *>(angfft_data), n2, ostride2, odist2,
                                FFTW_FORWARD, FFTW_ESTIMATE); // create the FFT plan

    int frame = 1;
    int maxidx = 0;
}

void RangeDoppler::remove_zero_dop(float *rdm_avg, float *zero_rdm_avg)
{
    for (int i = 0; i < SLOW_TIME * FAST_TIME; i++)
    {
        zero_rdm_avg[i] = rdm_avg[i];
    }
    for (int i = 32; i < 34; i++)
    {
        for (int j = 0; j < FAST_TIME; j++)
        {
            int idx = i * FAST_TIME + j;
            zero_rdm_avg[idx] = 0;
        }
    }

    // 31-34 doppler frames need to be 0 out of 64,
}

int RangeDoppler::compute_angle_est()
{
    fftwf_execute(plan2);
    return 0;
}

int RangeDoppler::compute_angmag_norm(std::complex<float> *rdm_complex, float *rdm_magnitude)
{
    float norm, log;
    std::complex<float> val;
    for (int i = 0; i < 96; i++)
    {
        val = rdm_complex[i];
        norm = std::norm(val);
        log = log2f(norm) / 2.0f;
        rdm_magnitude[i] = log;
    }
    return 0;
}

void RangeDoppler::find_azimuth_angle(float *angle_norm, float *final_angle)
{
    float step = 180 / 16;
    float data[16];
    for (int i = 0; i < 16; i++)
    {
        data[i] = angle_norm[48 + i];
    }
    float max = *std::max_element(data, data + 16);
    for (int i = 0; i < 16; i++)
    {
        if (angle_norm[48 + i] == max)
        {
            final_angle[0] = step * i - 90; // add -90 if you want fft shift
        }
    }
}

/*
    void correlation_matrix(float* rdm_avg, float* prev_rdm_avg, float* cfar_cube, std::complex<float>* adc_data, int* cfar_max, std::complex<float>* Rmatrix, float* final_range) {

        cfar_max[0] = cfar_matrix(rdm_avg, prev_rdm_avg, cfar_cube);
        int maxidx = cfar_max[0];

        float multiplier = 9.0f / 256.0f;
        float rangebin = (maxidx%FAST_TIME) * multiplier;
        final_range[0] = rangebin;

        std::complex<float> indices[12] = {0};
        //getADCindices(maxidx, indices);

        getADCaverage(maxidx, indices, adc_data);

        std::complex<float> xn_values[8] = {0};
        for(int i=0; i<4; i++) {
        //xn_values[i] = adc_data[indices[i]];
        //xn_values[i+4] = adc_data[indices[i+4]];
        xn_values[i] = indices[i];
        xn_values[i+4] = indices[i+4];
        }

        // Create a 8 by 1 matrix from the array
        Eigen::Matrix<std::complex<float>,8,1> xnMat; // This is x[n]

        // Initialize the matrix from the array
        for (int i = 0; i < 8; ++i) {
        xnMat(i,0) = xn_values[i];
        }
        Eigen::Matrix<std::complex<float>,1,8> xnHermitian = xnMat.adjoint(); // This is xH[n]

        Eigen::Matrix<std::complex<float>,8,8> corr_matrix = xnMat * xnHermitian;

        for (size_t i = 0; i < 8; ++i) {
            for (size_t j = 0; j < 8; ++j) {
                int idx = i*8;
                Rmatrix[idx + j] = corr_matrix(i,j);
            }
        }


        output_energy(Rmatrix, cfar_max);


    }


    void output_energy(std::complex<float>* Rmatrix, int* cfar_max) {

        Eigen::Matrix<std::complex<float>,8,8> Rmat;
        for (size_t i = 0; i < 8; ++i) {
            for (size_t j = 0; j < 8; ++j) {
                int idx = i*8;
                Rmat(i,j) = Rmatrix[idx + j];
            }
        }
        Eigen::Matrix<std::complex<float>,8,8> RinvMat = Rmat.inverse();

        vector<vector<std::complex<float>>> steering(8, vector<std::complex<float>>(1));
        Eigen::Matrix<std::complex<float>,8,1> steer;
        vector<std::complex<float>> outpower;


        for (int ang = -90; ang < 92; ang+=2) {
            vector<vector<std::complex<float>>> steering_vect = steering_mat(steering, ang);

            for (size_t i = 0; i < 8; ++i) {
                steer(i,0) = steering_vect[i][0];
            }
            Eigen::Matrix<std::complex<float>,1,8> conjtrans = steer.adjoint();
            Eigen::Matrix<std::complex<float>,1,1> someMatrix = conjtrans * RinvMat * steer;
            std::complex<float> complexOne(1,0);

            std::complex<float> outputpower = complexOne / someMatrix(0,0);
            outpower.push_back(outputpower);
        }

        float powermag = 0;
        int idxmaxmag;

        for (int i = 0; i < outpower.size(); i++) {
            float magnitude = abs(outpower[i]);
            if (magnitude > powermag) {
                powermag = magnitude;
                idxmaxmag = i;
            }

        }

        std::cout << "Index of the complex number with the maximum magnitude: " << idxmaxmag*2 - 90 << std::endl;
        //cfar_max[0] = idxmaxmag*2 - 90;

    }

    vector<vector<std::complex<float>>> steering_mat(vector<vector<std::complex<float>>>& matrix, int angle) {

        std::complex<float> im(0.0,1.0);
        double anglerad = angle * (M_PI / 180);
        float sineval = sin(anglerad);
        float NPI = n_pi;
        for (size_t i = 0; i < matrix.size(); ++i) {
            float inc = i;
            matrix[i][0] = exp(-im*NPI*sineval*inc);
        }

        return matrix;

    }
*/

void RangeDoppler::correlation_matrix(float *rdm_avg, float *prev_rdm_avg, float *cfar_cube, std::complex<float> *adc_data, int *cfar_max, std::complex<float> *Rmatrix, float *final_range, float *final_angle)
{

    cfar_max[0] = cfar_matrix(rdm_avg, prev_rdm_avg, cfar_cube);
    int maxidx = cfar_max[0];
    /*
    string filename = "/home/fusionsense/repos/AVR/RadarPipeline/test/non_thread/matrix.txt";
    ofstream file;
    file.open(filename, ios::app);
    for (int i=0; i<SIZE; i++) {
        file << adc_data[i] << " ";
    }
    file << endl;
    file << maxidx << endl;
    file.close();

    Document jsondoc;
    jsondoc.SetArray();
    for (int i=0; i<SIZE; i++) {
        Value adcval(kObjectType);
        adcval.AddMember("real", adc_data[i].real(), jsondoc.GetAllocator());
        adcval.AddMember("imaginary", adc_data[i].imag(), jsondoc.GetAllocator());
        jsondoc.PushBack(adcval, jsondoc.GetAllocator());
    }

    StringBuffer buffer;
    Writer<StringBuffer> writer(buffer);
    jsondoc.Accept(writer);
    ofstream ofs("output.json");
    ofs << buffer.GetString();
    ofs.close();
    */

    float multiplier = 9.0f / 256.0f;
    float rangeval = (maxidx % FAST_TIME) * multiplier;
    final_range[0] = rangeval;

    const int range_bin = (maxidx % FAST_TIME) - 1;
    const int RD_bins = SLOW_TIME * FAST_TIME;

    Eigen::Matrix<std::complex<float>, 12, 12> sum_mat;
    sum_mat.setZero();

    for (int j = range_bin; j < RD_bins; j += FAST_TIME)
    {

        std::complex<float> xn_values[12] = {0};
        getADCaverage(j, xn_values, adc_data);

        // Create a 8 by 1 matrix from the array
        Eigen::Matrix<std::complex<float>, 12, 1> xnMat; // This is x[n]

        // Initialize the matrix from the array
        for (int i = 0; i < 12; ++i)
        {
            xnMat(i, 0) = xn_values[i];
        }
        Eigen::Matrix<std::complex<float>, 1, 12> xnHermitian = xnMat.adjoint(); // This is xH[n]
        Eigen::Matrix<std::complex<float>, 12, 12> corr_matrix = xnMat * xnHermitian;

        sum_mat = sum_mat + corr_matrix;
    }

    std::complex<float> complexsixfour(64, 0);
    for (size_t i = 0; i < 12; ++i)
    {
        for (size_t j = 0; j < 12; ++j)
        {
            int idx = i * 12;
            Rmatrix[idx + j] = sum_mat(i, j) / complexsixfour;
        }
    }

    output_energy(Rmatrix, cfar_max, final_angle);
}

void RangeDoppler::output_energy(std::complex<float> *Rmatrix, int *cfar_max, float *final_angle)
{

    Eigen::Matrix<std::complex<float>, 12, 12> Rmat;
    for (size_t i = 0; i < 12; ++i)
    {
        for (size_t j = 0; j < 12; ++j)
        {
            int idx = i * 12;
            Rmat(i, j) = Rmatrix[idx + j];
        }
    }
    Eigen::Matrix<std::complex<float>, 12, 12> RinvMat = Rmat.inverse();

    // vector<vector<std::complex<float>>> steering(8, vector<std::complex<float>>(1));
    // Eigen::Matrix<std::complex<float>,8,1> steer;
    std::vector<std::complex<float>> outpower;

    for (int ang = -90; ang < 91; ang += 1)
    {
        // vector<vector<std::complex<float>>> steering_vect = steering_mat(steering, ang);

        // for (size_t i = 0; i < 8; ++i) {
        //	steer(i,0) = steering_vect[i][0];
        // }

        Eigen::Matrix<std::complex<float>, 12, 1> steer = steering_mat(ang);

        Eigen::Matrix<std::complex<float>, 1, 12> conjtrans = steer.adjoint();

        Eigen::Matrix<std::complex<float>, 1, 1> someMatrix = conjtrans * RinvMat * steer;

        std::complex<float> complexOne(1, 0);

        std::complex<float> outputpower = complexOne / someMatrix(0, 0);
        outpower.push_back(outputpower);
    }

    float powermag = 0;
    int idxmaxmag;

    for (int i = 0; i < outpower.size(); i++)
    {
        float magnitude = abs(outpower[i]);
        if (magnitude > powermag)
        {
            powermag = magnitude;
            idxmaxmag = i;
        }
    }

    std::cout << "Index of the complex number with the maximum magnitude: " << idxmaxmag - 90 << std::endl;
    // cfar_max[0] = idxmaxmag*2 - 90;
    // final_angle[0] = idxmaxmag - 90;
}

Eigen::Matrix<std::complex<float>, 12, 1> RangeDoppler::steering_mat(int angle)
{

    std::complex<float> im(0.0, 1.0);
    double anglerad = angle * (M_PI / 180);
    float sineval = sin(anglerad);
    float cosval = cos(anglerad);
    double elev_angle = 0 * (M_PI / 180);
    float sinelev = sin(elev_angle);
    float coselev = cos(elev_angle);
    float NPI = n_pi;

    Eigen::Matrix<std::complex<float>, 12, 1> matrix;
    Eigen::Matrix<std::complex<float>, 16, 1> matrix16;

    int count = 0;
    for (int n = 0; n < 8; n++)
    {
        for (int k = 0; k < 2; k++)
        {
            float nf = n;
            float kf = k;
            matrix16(count, 0) = exp(im * NPI * (nf * sineval * coselev + kf * sineval * sinelev));
            count = count + 1;
        }
    }

    // int idx[] = {1, 3, 13, 15};
    int idx[] = {1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15};
    int idxsize = sizeof(idx) / sizeof(idx[0]);
    for (int i = 0; i < idxsize; i++)
    {
        matrix(i, 0) = matrix16(idx[i], 0);
    }

    /*
    for (size_t i = 0; i < matrix.size(); ++i) {
        float inc = i;
        matrix(i,0) = exp(-im*NPI*sineval*inc);
    }
    */

    return matrix;
}

void RangeDoppler::getADCaverage(int index_1D, std::complex<float> *xnvalues, std::complex<float> *adc_data)
{
    const int RD_bins = SLOW_TIME * FAST_TIME;
    for (int i = 0; i < TX * RX; i++)
    {
        xnvalues[i] = adc_data[i * RD_bins + index_1D];
    }
}

float *RangeDoppler::getRangeBufferPointer()
{
    return final_range; // getting range values
}

float *RangeDoppler::getAngleBufferPointer()
{
    return final_angle; // find_azimuth_angle(angle_norm);
}

int *RangeDoppler::getAngleIndexPointer()
{
    return cfar_max; // find_azimuth_angle(angle_norm);
}

float* RangeDoppler::getAngleMapPointer()
	{
	    return angle_norm; // getting range values
	}

	float* RangeDoppler::getDopplerBufferPointer()
	{
	    return final_doppler; // getting doppler velocity in m/s
	}

	int* RangeDoppler::getDopplerBinPointer()
	{
	    return final_doppler_bin; // getting raw doppler bin index
	}

	float* RangeDoppler::getRDMDataPointer()
	{
	    return zero_rdm_avg; // getting the full range-doppler map data
	}

	// Calculate doppler velocity from bin index
	void RangeDoppler::compute_doppler_velocity(int cfar_idx) {
	    // Get the doppler bin (slow time dimension)
	    int doppler_bin = cfar_idx / FAST_TIME;
	    
	    // Shift to center (fftshift was applied, so center bin is at SLOW_TIME/2)
	    // After fftshift, bin 0 corresponds to most negative velocity
	    // bin SLOW_TIME/2 corresponds to zero velocity
	    // bin SLOW_TIME-1 corresponds to most positive velocity
	    int shifted_bin = doppler_bin - SLOW_TIME/2;
	    
	    // Calculate velocity: positive = approaching, negative = receding
	    float velocity = shifted_bin * VELOCITY_RES;
	    
	    final_doppler[0] = velocity;
	    final_doppler_bin[0] = doppler_bin;
	    
	    std::cout << "Doppler bin: " << doppler_bin << ", Velocity: " << velocity << " m/s" << std::endl;
	}

	// Save RDM data to binary file for Python plotting
	int RangeDoppler::save_rdm_data(const std::string& filename) {
	    std::ofstream outfile(filename, std::ios::binary);
	    if (!outfile.is_open()) {
	        std::cerr << "Error: Could not open file " << filename << std::endl;
	        return -1;
	    }
	    
	    // Write header: dimensions
	    int dims[2] = {SLOW_TIME, FAST_TIME};
	    outfile.write(reinterpret_cast<char*>(dims), sizeof(dims));
	    
	    // Write the RDM data
	    outfile.write(reinterpret_cast<char*>(zero_rdm_avg), SLOW_TIME * FAST_TIME * sizeof(float));
	    
	    outfile.close();
	    return 0;
	}

// Still need to fix this fftshift issue
void RangeDoppler::fftshift_ang_est(float *arr)
{
    int midRow = 16 / 2;
    int midColumn = 6 / 2;
    float fftshifted[96];

    for (int i = 0; i < 16; i++)
    {
        for (int j = 0; j < 6; j++)
        {
            int newRow = (i + midRow) % 16;              // ROW WISE FFTSHIFT
            int newColumn = (j + midColumn) % 6;         // COLUMN WISE FFTSHIFT
            fftshifted[newRow * 6 + j] = arr[i * 6 + j]; // only newRow is used so only row wise fftshift
        }
    }
    for (int i = 0; i < 96; i++)
        arr[i] = fftshifted[i];
}

/*
        void fftshift_rdm(float* arr){
            int midRow = FAST_TIME / 2;
            int midColumn = SLOW_TIME / 2;
            float fftshifted[SLOW_TIME*FAST_TIME];

            for (int i = 0; i < FAST_TIME; i++) {
                for (int j = 0; j < SLOW_TIME; j++) {
                    int newRow = (i + midRow) % FAST_TIME;          // ROW WISE FFTSHIFT
                    int newColumn = (j + midColumn) % SLOW_TIME;    // COLUMN WISE FFTSHIFT
                    fftshifted[newRow * SLOW_TIME + j] = arr[i * SLOW_TIME + j]; // only newRow is used so only row wise fftshift
                }
            }
            for(int i = 0; i < FAST_TIME*SLOW_TIME; i++)
                arr[i] = fftshifted[i];
        }
*/

int RangeDoppler::cfar_matrix(float *rdm_avg, float *prev_rdm_avg, float *cfar_cube)
{
    for (int i = 0; i < SLOW_TIME * FAST_TIME; i++)
    {
        cfar_cube[i] = rdm_avg[i] - prev_rdm_avg[i];
    }
    float max = *std::max_element(cfar_cube, cfar_cube + SLOW_TIME * FAST_TIME);
    float threshold = max;
    for (int i = 0; i < SLOW_TIME * FAST_TIME; i++)
    {
        if (cfar_cube[i] >= threshold)
        {
            cfar_cube[i] = 1;
            return i;
        }
        else
        {
            cfar_cube[i] = 0;
        }
    }
}

void RangeDoppler::getADCindices(int index_1D, int *indices)
{
    const int RD_bins = SLOW_TIME * FAST_TIME;
    for (int i = 0; i < TX * RX; i++)
    {
        indices[i] = i * RD_bins + index_1D;
    }
}

float RangeDoppler::mean_noise_rdm(float *rdm_avg)
{
    float MNF = 0;
    for (int i = 0; i < SLOW_TIME * FAST_TIME; i++)
    {
        MNF = MNF + rdm_avg[i];
    }
    MNF = MNF / (SLOW_TIME * FAST_TIME);
    return MNF;
}

void RangeDoppler::shape_angle_data(float *rdm_avg, float *prev_rdm_avg, float *cfar_cube, std::complex<float> *adc_data, std::complex<float> *angle_data, int *cfar_max)
{

    cfar_max[0] = cfar_matrix(rdm_avg, prev_rdm_avg, cfar_cube);
    int maxidx = cfar_max[0];
    // std::cout << "max index: " << maxidx%FAST_TIME << std::endl;

    int indices[12] = {0};
    getADCindices(maxidx, indices);

    for (int i = 0; i < 32; i++)
    {
        angle_data[i] = 0;
        angle_data[i + 64] = 0;
    }
    for (int i = 0; i < 16; i++)
    {
        if (i < 6 || i > 9)
        {
            angle_data[i + 32] = 0;
        }
        else
        {
            angle_data[i + 32] = adc_data[indices[4 + (i - 6)]];
        }
        if (i < 4 || i > 11)
        {
            angle_data[i + 48] = 0;
        }
        else if (i >= 4 && i < 8)
        {
            angle_data[i + 48] = adc_data[indices[0 + (i - 4)]];
        }
        else
        {
            angle_data[i + 52] = adc_data[indices[8 + (i - 8)]];
        }
    }
}

// Retrieve outputbuffer pointer
float *RangeDoppler::getBufferPointer()
{
    return zero_rdm_avg;
}

void RangeDoppler::setBufferPointer(uint16_t *arr)
{
    input = arr;
}

// FILE READING METHODS
void RangeDoppler::readFile(const std::string &filename)
{ //
    std::ifstream file(filename);
    if (file.is_open())
    {
        std::string line;

        int i = 0;
        while (std::getline(file, line))
        {
            if (i > SIZE_W_IQ)
            {
                std::cerr << "Error: More samples than SIZE " << filename << std::endl;
                break;
            }
            float value = std::stof(line);
            adc_data_flat[i] = value;
            i++;
        }
        std::cout << "File Successfully read!" << std::endl;
        file.close();
    }
    else
    {
        std::cerr << "Error: Could not open file " << filename << std::endl;
    }
}

int RangeDoppler::save_1d_array(float *arr, int width, int length, std::string &filename)
{
    std::ofstream outfile(filename);
    for (int i = 0; i < length * width; i++)
    {
        outfile << arr[i] << std::endl;
    }

    // outfile.close();
    std::cout << "Array saved to file. " << std::endl;
    return 0;
}

// WINDOW TYPES
void RangeDoppler::blackman_window(float *arr, int fast_time)
{
    for (int i = 0; i < fast_time; i++)
        arr[i] = 0.42 - 0.5 * cos(2 * M_PI * i / (fast_time - 1)) + 0.08 * cos(4 * M_PI * i / (fast_time - 1));
}

void RangeDoppler::hann_window(float *arr, int fast_time)
{
    for (int i = 0; i < fast_time; i++)
        arr[i] = 0.5 * (1 - cos((2 * M_PI * i) / (fast_time - 1)));
}

void RangeDoppler::no_window(float *arr, int fast_time)
{
    for (int i = 0; i < fast_time; i++)
        arr[i] = 1;
}

void RangeDoppler::setSNR(float maxSNR, float minSNR)
{
    SET_SNR = true;
    max = maxSNR;
    min = minSNR;
}
// output indices --> {IQ, FAST_TIME, SLOW_TIME, RX, TX}
void RangeDoppler::getIndices(int index_1D, int *indices)
{
    int i0 = index_1D / (RX * IQ * FAST_TIME * TX);
    int i1 = index_1D % (RX * IQ * FAST_TIME * TX);
    int i2 = i1 % (RX * IQ * FAST_TIME);
    int i3 = i2 % (RX * IQ);
    int i4 = i3 % (RX);

    indices[2] = i0;                         // SLOW_TIME | Chirp#
    indices[0] = i1 / (RX * IQ * FAST_TIME); // TX#
    indices[3] = i2 / (RX * IQ);             // FAST_TIME | Range#
    indices[4] = i3 / (RX);                  // IQ
    indices[1] = i4;                         // RX#
}

void RangeDoppler::shape_cube(float *in, float *mid, std::complex<float> *out)
{
    int rx = 0;
    int tx = 0;
    int iq = 0;
    int fast_time = 0;
    int slow_time = 0;
    int indices[5] = {0};
    float window[FAST_TIME];
    if (strcmp(WINDOW_TYPE, "blackman") == 0)
        blackman_window(window, FAST_TIME);
    else if (strcmp(WINDOW_TYPE, "hann") == 0)
        hann_window(window, FAST_TIME);
    else
        no_window(window, FAST_TIME);

    for (int i = 0; i < SIZE_W_IQ; i++)
    {
        getIndices(i, indices);
        tx = indices[0] * RX * SLOW_TIME * FAST_TIME * IQ;
        rx = indices[1] * SLOW_TIME * FAST_TIME * IQ;
        slow_time = indices[2] * FAST_TIME * IQ;
        fast_time = indices[3] * IQ;
        iq = indices[4];
        mid[tx + rx + slow_time + fast_time + iq] = in[i] * window[fast_time / IQ];
    }

    for (int i = 0; i < SIZE; i++)
    {
        out[i] = std::complex<float>(mid[2 * i + 0], mid[2 * i + 1]);
    }
}

int RangeDoppler::compute_range_doppler()
{
    fftwf_execute(plan);
    return 0;
}

void RangeDoppler::scale_rdm_values(float *arr, float max_val, float min_val)
{
    // fill in the matrix with the values scaled to 0-255 range
    for (int i = 0; i < FAST_TIME * SLOW_TIME; i++)
    {
        arr[i] = (arr[i] - min_val) / (max_val - min_val) * 255;
        if (arr[i] < 0)
            arr[i] = 0;
    }
}

void RangeDoppler::fftshift_rdm(float *arr)
{
    int midRow = FAST_TIME / 2;
    int midColumn = SLOW_TIME / 2;
    float fftshifted[SLOW_TIME * FAST_TIME];

    for (int i = 0; i < FAST_TIME; i++)
    {
        for (int j = 0; j < SLOW_TIME; j++)
        {
            int newRow = (i + midRow) % FAST_TIME;                       // ROW WISE FFTSHIFT
            int newColumn = (j + midColumn) % SLOW_TIME;                 // COLUMN WISE FFTSHIFT
            fftshifted[newRow * SLOW_TIME + j] = arr[i * SLOW_TIME + j]; // only newRow is used so only row wise fftshift
        }
    }
    for (int i = 0; i < FAST_TIME * SLOW_TIME; i++)
        arr[i] = fftshifted[i];
}

int RangeDoppler::compute_mag_norm(std::complex<float> *rdm_complex, float *rdm_magnitude)
{
    float norm, log;
    std::complex<float> val;
    for (int i = 0; i < SIZE; i++)
    {
        val = rdm_complex[i];
        norm = std::norm(val);
        log = log2f(norm) / 2.0f;
        rdm_magnitude[i] = log;
        // print out values to text file here, write python script to generate heatmap with the values from text file
    }
    return 0;
}
// rdm_avg should be zero-filled
int RangeDoppler::averaged_rdm(float *rdm_norm, float *rdm_avg)
{
    int idx;
    const int VIRT_ANTS = TX * RX;
    const int RD_BINS = SLOW_TIME * FAST_TIME;
    if (!SET_SNR)
    {
        float max, min;
    }
    for (int i = 0; i < (VIRT_ANTS); i++)
    {
        for (int j = 0; j < (RD_BINS); j++)
        {
            idx = i * (RD_BINS) + j;
            if (i == 0)
                rdm_avg[j] = 0;
            rdm_avg[j] += rdm_norm[idx] / ((float)RD_BINS);
            if (i == (VIRT_ANTS - 1) && !SET_SNR)
            {
                if (j == 0)
                {
                    max = rdm_avg[0];
                    min = rdm_avg[0];
                }

                if (rdm_avg[j] > max)
                    max = rdm_avg[j];
                else if (rdm_avg[j] < min)
                    min = rdm_avg[j];
            }
        }
    }

    // std::cout << "MAX: " << max << "      |        MIN:  " << min << std::endl;

    scale_rdm_values(rdm_avg, max, min);
    fftshift_rdm(rdm_avg);
    return 0;
}

void RangeDoppler::process()
{
    // auto start = chrono::high_resolution_clock::now();
    for (int i = 0; i < SIZE_W_IQ; i++)
    {
        adc_data_flat[i] = (float)input[i];
    }
    if (frame <= 1)
    {
        for (int i = 0; i < SLOW_TIME * FAST_TIME; i++)
        {
            prev_rdm_avg[i] = 0;
        }
    }
    else
    {
        for (int i = 0; i < SLOW_TIME * FAST_TIME; i++)
        {
            prev_rdm_avg[i] = zero_rdm_avg[i];
        }
    }
    shape_cube(adc_data_flat, adc_data_reshaped, adc_data);
    compute_range_doppler();
    compute_mag_norm(rdm_data, rdm_norm);
    averaged_rdm(rdm_norm, rdm_avg);
    remove_zero_dop(rdm_avg, zero_rdm_avg);
    shape_angle_data(zero_rdm_avg, prev_rdm_avg, cfar_cube, adc_data, angle_data, cfar_max);
    correlation_matrix(zero_rdm_avg, prev_rdm_avg, cfar_cube, adc_data, cfar_max, Rmatrix, final_range, final_angle);
    compute_angle_est();
    compute_angmag_norm(angfft_data, angle_norm);
    // fftshift_ang_est(angle_norm);
    find_azimuth_angle(angle_norm, final_angle);

    // string str = ("./out") + to_string(frame) + ".txt";
    // save_1d_array(rdm_avg, FAST_TIME, SLOW_TIME, str);

    // auto stop = chrono::high_resolution_clock::now();
    // auto duration_rdm_process = duration_cast<microseconds>(stop - start);
    // std::cout << "RDM Process Time " << duration_rdm_process.count() << " microseconds" << std::endl;

    frame++;
    std::cout << "Frame: " << frame << std::endl;
}
