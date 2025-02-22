<?php
ob_start();

// Set the default timezone to Philippines time
date_default_timezone_set('Asia/Manila');

include_once 'connectdb.php';
session_start();
include_once "header.php";



// Check if employee is logged in
if (!isset($_SESSION['employee_id'])) {
    header("Location: login.php");
    exit();
}

// Function to populate product dropdown
function fill_product($pdo)
{
    $output = '';
    try {
        $select = $pdo->prepare("SELECT product_id, product_name FROM products ORDER BY product_name ASC");
        $select->execute();
        while ($row = $select->fetch(PDO::FETCH_ASSOC)) {
            $output .= '<option value="' . htmlspecialchars($row["product_id"]) . '">'
                . htmlspecialchars($row["product_name"]) . '</option>';
        }
    } catch (PDOException $e) {
        error_log("Database Error: " . $e->getMessage());
    }
    return $output;
}

// Order Processing Logic
if (isset($_POST['btnsaveorder'])) {
    try {
        // Validate session and permissions
        if (!isset($_SESSION['employee_id'])) {
            throw new Exception("Unauthorized access");
        }

        // Get employee ID from session
        $employee_id = $_SESSION['employee_id'];

        // Get order details (using Philippines time)
        $order_date = date('Y-m-d');
        $order_time = date('H:i:s');

        // Sanitize financial inputs
        $subtotal = filter_var($_POST['txtsubtotal'], FILTER_SANITIZE_NUMBER_FLOAT, FILTER_FLAG_ALLOW_FRACTION);
        $discount = filter_var($_POST['txtdiscount'], FILTER_SANITIZE_NUMBER_FLOAT, FILTER_FLAG_ALLOW_FRACTION);
        $total = filter_var($_POST['txttotal'], FILTER_SANITIZE_NUMBER_FLOAT, FILTER_FLAG_ALLOW_FRACTION);
        $payment_type = htmlspecialchars($_POST['rb']);

        // Ensure payment type is only cash
        if ($payment_type !== 'Cash') {
            throw new Exception("Invalid payment type. Only cash payments are allowed.");
        }

        $paid = filter_var($_POST['txtpaid'], FILTER_SANITIZE_NUMBER_FLOAT, FILTER_FLAG_ALLOW_FRACTION);
        $due = max($total - $paid, 0);

        // Process product arrays (each hidden field holds a CSV string)
        // Note: The hidden input names no longer use array notation.
        $pid_csv = $_POST['pid_arr'] ?? '';
        $arr_product_id = array_map('intval', explode(',', $pid_csv));

        $qty_csv = $_POST['quantity_arr'] ?? '';
        $arr_qty = array_map('intval', explode(',', $qty_csv));

        $price_csv = $_POST['price_c_arr'] ?? '';
        $arr_price = array_map('floatval', explode(',', $price_csv));

        $total_csv = $_POST['saleprice_arr'] ?? '';
        $arr_total = array_map('floatval', explode(',', $total_csv));

        // Validate that there is at least one product in the order
        if (empty($arr_product_id) || $arr_product_id[0] === 0) {
            throw new Exception("No products in order");
        }

        // Start database transaction
        $pdo->beginTransaction();

        // Insert into invoices table
        $invoice_stmt = $pdo->prepare("INSERT INTO invoices 
            (employee_id, order_date, order_time, subtotal, discount, total, paid, due, payment_type)
            VALUES (:employee_id, :order_date, :order_time, :subtotal, :discount, :total, :paid, :due, :payment_type)");

        $invoice_stmt->execute([
            ':employee_id'   => $employee_id,
            ':order_date'    => $order_date,
            ':order_time'    => $order_time,
            ':subtotal'      => $subtotal,
            ':discount'      => $discount,
            ':total'         => $total,
            ':paid'          => $paid,
            ':due'           => $due,
            ':payment_type'  => $payment_type
        ]);

        $invoice_id = $pdo->lastInsertId();
        if (!$invoice_id) {
            throw new Exception("Failed to insert invoice record.");
        }

        // Process each product in the order
        // Process each product in the order
        foreach ($arr_product_id as $index => $product_id) {
            $qty = $arr_qty[$index] ?? 0;
            $price = $arr_price[$index] ?? 0;
            $total_price = $arr_total[$index] ?? 0;

            // Validate product existence with row lock
            $product_check = $pdo->prepare("SELECT stock, sale_price 
        FROM products 
        WHERE product_id = ? 
        FOR UPDATE");
            $product_check->execute([$product_id]);


            $product = $product_check->fetch(PDO::FETCH_ASSOC);

            if (!$product) {
                throw new Exception("Invalid product ID: $product_id");
            }

            // Validate price consistency
            if (abs($price - $product['sale_price']) > 0.01) {
                throw new Exception("Price mismatch for product ID: $product_id");
            }

            // Atomic stock update with integrity check
            $update_stock = $pdo->prepare("UPDATE products 
        SET stock = stock - :qty 
        WHERE product_id = :product_id 
          AND stock >= :min_qty");
            $update_stock->execute([
                ':qty' => $qty,
                ':product_id' => $product_id,
                ':min_qty' => $qty
            ]);

            if ($update_stock->rowCount() === 0) {
                throw new Exception("Insufficient stock for product ID: $product_id");
            }

            // Insert into invoice details
            $detail_stmt = $pdo->prepare("INSERT INTO invoice_details 
        (invoice_id, product_id, quantity, unit_price, total_price)
        VALUES (?, ?, ?, ?, ?)");
            $detail_stmt->execute([
                $invoice_id,
                $product_id,
                $qty,
                $price,
                $total_price
            ]);
        }

        // Commit transaction
        $pdo->commit();

        // Clear any output buffer before printing
        ob_end_clean();
?>
        <html>

        <head>
            <!-- Include SweetAlert2 if not already included -->
            <script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
        </head>

        <body>
            <script>
                // Show a modal asking if the user wants to print the receipt
                Swal.fire({
                    title: 'Invoice Saved!',
                    text: 'Do you want to print the receipt?',
                    icon: 'success',
                    showCancelButton: true,
                    confirmButtonText: 'Print Now',
                    cancelButtonText: 'Save Invoice'
                }).then((result) => {
                    if (result.isConfirmed) {
                        // Open the receipt in a new window/tab if "Print Now" is clicked
                        window.open("printbill.php?id=<?= $invoice_id ?>", "_blank");
                    }
                    // In either case, reload the POS page (or redirect as desired)
                    window.location.href = "pos.php";
                });
            </script>
        </body>

        </html>
<?php
        exit();
    } catch (PDOException $e) {
        if ($pdo->inTransaction()) {
            $pdo->rollBack();
        }
        error_log("Database Error: " . $e->getMessage());
        die("Order processing failed: " . $e->getMessage());
    } catch (Exception $e) {
        if ($pdo->inTransaction()) {
            $pdo->rollBack();
        }
        error_log("Order Error: " . $e->getMessage());
        die($e->getMessage());
    }
}

ob_end_flush();
?>

<!DOCTYPE html>
<html lang="en">

<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>School Store POS</title>
    <!-- Include additional CSS files as needed (e.g., Bootstrap, Select2) -->
</head>

<body class="hold-transition sidebar-mini layout-fixed">
    <div class="wrapper">
        <!-- Main content section -->
        <div class="content-wrapper">
            <section class="content">
                <div class="container-fluid">
                    <div class="row">
                        <div class="col-md-12">
                            <div class="card card-primary">
                                <div class="card-header">
                                    <h3 class="card-title">New Order</h3>
                                </div>
                                <!-- POS Interface -->
                                <div class="card-body">
                                    <form method="post" id="posForm">
                                        <div class="row">
                                            <!-- Product Selection Column -->
                                            <div class="col-md-8">
                                                <!-- Barcode Input -->
                                                <div class="input-group mb-3">
                                                    <div class="input-group-prepend">
                                                        <span class="input-group-text"><i class="fas fa-barcode"></i></span>
                                                    </div>
                                                    <input type="text" class="form-control"
                                                        id="txtbarcode"
                                                        name="txtbarcode"
                                                        placeholder="Scan Barcode"
                                                        autocomplete="off"
                                                        autofocus>
                                                    <div class="input-group-append">
                                                        <button type="button" class="btn btn-secondary" id="clearBarcode">Clear</button>
                                                    </div>
                                                </div>
                                                <!-- Product Dropdown -->
                                                <select class="form-control select2" id="productSelect">
                                                    <option value="">Select Product</option>
                                                    <?= fill_product($pdo) ?>
                                                </select>
                                                <!-- Order Items Table -->
                                                <div class="tableFixHead mt-3">
                                                    <table class="table table-bordered">
                                                        <thead class="thead-light">
                                                            <tr>
                                                                <th>Product</th>
                                                                <!-- Display remaining stock (original stock minus ordered quantity) -->
                                                                <th>Remaining Stock</th>
                                                                <th>Price</th>
                                                                <th>Quantity</th>
                                                                <th>Total</th>
                                                                <th>Action</th>
                                                            </tr>
                                                        </thead>
                                                        <tbody id="orderItems">
                                                            <!-- Dynamic content from JavaScript -->
                                                        </tbody>
                                                    </table>
                                                </div>
                                            </div>
                                            <!-- Payment Section -->
                                            <div class="col-12 col-md-4">
                                                <div class="bg-light p-3 rounded">
                                                    <!-- Subtotal -->
                                                    <div class="form-group">
                                                        <label>Subtotal</label>
                                                        <div class="input-group">
                                                            <div class="input-group-prepend">
                                                                <span class="input-group-text">₱</span>
                                                            </div>
                                                            <input type="text" class="form-control" id="subtotal" name="txtsubtotal" readonly>
                                                        </div>
                                                    </div>
                                                    <!-- Discount -->
                                                    <div class="form-group">
                                                        <label>Discount (%)</label>
                                                        <input type="number" class="form-control" id="txtdiscount" name="txtdiscount" min="0" max="100" value="0">
                                                    </div>
                                                    <!-- Total -->
                                                    <div class="form-group">
                                                        <label>Total</label>
                                                        <div class="input-group">
                                                            <div class="input-group-prepend">
                                                                <span class="input-group-text">₱</span>
                                                            </div>
                                                            <input type="text" class="form-control" id="total" name="txttotal" readonly>
                                                        </div>
                                                    </div>
                                                    <!-- Payment Type (Only Cash is available) -->
                                                    <div class="form-group">
                                                        <label>Payment Type</label>
                                                        <div class="btn-group btn-group-toggle w-100" data-toggle="buttons">
                                                            <label class="btn btn-outline-success active">
                                                                <input type="radio" name="rb" value="Cash" checked> Cash
                                                            </label>
                                                        </div>
                                                    </div>
                                                    <!-- Amount Paid -->
                                                    <div class="form-group">
                                                        <label>Amount Paid</label>
                                                        <div class="input-group">
                                                            <div class="input-group-prepend">
                                                                <span class="input-group-text">₱</span>
                                                            </div>
                                                            <input type="number" class="form-control" id="txtpaid" name="txtpaid" step="0.01" required>
                                                        </div>
                                                    </div>
                                                    <!-- Change Due -->
                                                    <div class="form-group">
                                                        <label>Change Due</label>
                                                        <div class="input-group">
                                                            <div class="input-group-prepend">
                                                                <span class="input-group-text">₱</span>
                                                            </div>
                                                            <input type="text" class="form-control" id="due" name="txtdue" readonly>
                                                        </div>
                                                    </div>
                                                    <!-- Submit Button -->
                                                    <button type="submit" class="btn btn-success btn-lg btn-block mt-4" name="btnsaveorder" id="saveOrder">
                                                        Complete Order
                                                    </button>
                                                </div>
                                            </div>
                                            <!-- Hidden Fields for Product Data (CSV strings) -->
                                            <!-- Note: The names below no longer use [] so only one value is sent. -->
                                            <input type="hidden" name="pid_arr" id="pid_arr">
                                            <input type="hidden" name="quantity_arr" id="quantity_arr">
                                            <input type="hidden" name="price_c_arr" id="price_c_arr">
                                            <input type="hidden" name="saleprice_arr" id="saleprice_arr">
                                        </div>
                                    </form>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </section>
        </div>

        <?php include_once "footer.php"; ?>
    </div>

    <!-- ================== JAVASCRIPT SECTION ================== -->
    <script>
        $(document).ready(function() {
            let orderItems = [];

            // Initialize Select2
            $('#productSelect').select2({
                theme: 'bootstrap4',
                placeholder: "Search product...",
                minimumInputLength: 2
            });

            // Barcode Input Handler
            $('#txtbarcode').on('input', function() {
                let barcode = $(this).val().trim();
                if (barcode.length >= 3) {
                    fetchProduct(barcode, 'barcode');
                }
            });

            // Product Select Handler
            $('#productSelect').on('change', function() {
                let productId = $(this).val();
                if (productId) {
                    fetchProduct(productId, 'product');
                }
            });

            // Fetch Product Data via AJAX
            function fetchProduct(value, type) {
                $.ajax({
                    url: 'getproduct.php',
                    method: 'GET',
                    data: (type === 'barcode') ? {
                        barcode: value
                    } : {
                        id: value
                    },
                    dataType: 'json',
                    success: function(response) {
                        if (response.error) {
                            showError(response.error);
                            return;
                        }
                        addOrUpdateProduct(response);
                        updateCalculations();
                        clearInputs();
                    },
                    error: function(xhr) {
                        showError(xhr.responseJSON?.error || 'Product not found');
                    }
                });
            }

            // Add or update a product in orderItems array
            function addOrUpdateProduct(product) {
                // Look for an existing item by product_id
                let existingItem = orderItems.find(item => item.id === product.product_id);

                if (existingItem) {
                    if ((existingItem.qty + 1) > product.stock) {
                        showError('Exceeds available stock');
                        return;
                    }
                    existingItem.qty++;
                    existingItem.total = existingItem.qty * product.sale_price;
                } else {
                    if (product.stock < 1) {
                        showError('Product out of stock');
                        return;
                    }
                    orderItems.push({
                        id: product.product_id,
                        name: product.product_name,
                        stock: product.stock,
                        price: product.sale_price,
                        qty: 1,
                        total: product.sale_price
                    });
                }

                renderOrderItems();
                updateHiddenFields();
            }

            // Render Order Items Table
            function renderOrderItems() {
                $('#orderItems').empty();
                orderItems.forEach((item, index) => {
                    // Calculate remaining stock as original stock minus quantity ordered
                    let remainingStock = item.stock - item.qty;
                    let row = `
                        <tr data-id="${item.id}">
                            <td>${item.name}</td>
                            <td>${remainingStock}</td>
                            <td>₱${item.price.toFixed(2)}</td>
                            <td>
                                <input type="number" class="form-control qty-input" value="${item.qty}" min="1" max="${item.stock}" data-index="${index}">
                            </td>
                            <td>₱${item.total.toFixed(2)}</td>
                            <td>
                                <button class="btn btn-danger btn-sm remove-item" data-index="${index}">
                                    <i class="fas fa-trash"></i>
                                </button>
                            </td>
                        </tr>`;
                    $('#orderItems').append(row);
                });
            }

            // Update Hidden Form Fields (CSV strings)
            function updateHiddenFields() {
                $('#pid_arr').val(orderItems.map(item => item.id).join(','));
                $('#quantity_arr').val(orderItems.map(item => item.qty).join(','));
                $('#price_c_arr').val(orderItems.map(item => item.price).join(','));
                $('#saleprice_arr').val(orderItems.map(item => item.total).join(','));
            }

            // Update overall calculations (subtotal, total, due)
            function updateCalculations() {
                let subtotal = orderItems.reduce((sum, item) => sum + item.total, 0);
                let discountPercent = parseFloat($('#txtdiscount').val()) || 0;
                let discountAmount = subtotal * (discountPercent / 100);
                let total = subtotal - discountAmount;
                let paid = parseFloat($('#txtpaid').val()) || 0;
                let due = total - paid;

                $('#subtotal').val(subtotal.toFixed(2));
                $('#total').val(total.toFixed(2));
                $('#due').val(due.toFixed(2));
                updateHiddenFields();
            }

            // Event Listener: When quantity input changes, update that row and recalculate totals
            $('#orderItems').on('input', '.qty-input', function() {
                let index = $(this).data('index');
                let newQty = parseInt($(this).val());
                if (newQty > orderItems[index].stock) {
                    showError('Exceeds available stock');
                    $(this).val(orderItems[index].qty);
                    return;
                }
                orderItems[index].qty = newQty;
                orderItems[index].total = newQty * orderItems[index].price;
                updateCalculations();
                renderOrderItems();
            });

            // Event Listener: Remove item from order
            $('#orderItems').on('click', '.remove-item', function(e) {
                e.preventDefault();
                let index = $(this).data('index');
                orderItems.splice(index, 1);
                renderOrderItems();
                updateCalculations();
            });

            // Update calculations when discount or paid amount changes
            $('#txtdiscount, #txtpaid').on('input', updateCalculations);

            // Error handling function
            function showError(message) {
                $('#txtbarcode').addClass('invalid-barcode');
                setTimeout(() => $('#txtbarcode').removeClass('invalid-barcode'), 500);
                Swal.fire({
                    icon: 'error',
                    title: 'Error!',
                    text: message
                });
            }

            // Clear barcode input and reset product dropdown
            function clearInputs() {
                $('#txtbarcode').val('');
                $('#productSelect').val(null).trigger('change');
            }

            $('#clearBarcode').click(clearInputs);
        });
    </script>

    <!-- SweetAlert2 -->
    <script src="plugins/sweetalert2/sweetalert2.min.js"></script>

    <?php if (isset($_SESSION['status'])): ?>
        <script>
            $(function() {
                const Toast = Swal.mixin({
                    toast: true,
                    position: 'top center',
                    showConfirmButton: false,
                    timer: 3000
                });

                Toast.fire({
                    icon: '<?= $_SESSION['status_code'] ?>',
                    title: '<?= $_SESSION['status'] ?>'
                });
               
            });
        </script>
    <?php
        unset($_SESSION['status']);
        unset($_SESSION['status_code']);
    endif; ?>
</body>

</html>
